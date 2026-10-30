"""Task-state persistence backed by PowerContext.

PowerContext is the durable task-state store for this sample.  Each state
revision is appended as one memory entry whose text starts with ``SDD_STATE|``
followed by JSON.  A fresh process can therefore list the scope and recover the
latest state without any local process memory.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft

from .config import records_dir, state_db_path
from .models import TaskState

STATE_PREFIX = "SDD_STATE|"


class PowerContextStateStore:
    def __init__(
        self,
        *,
        db_path: Path | None = None,
        project_id: str = "sdd-order-demo",
        log_path: Path | None = None,
    ) -> None:
        self.db_path = (db_path or state_db_path()).resolve()
        self.project_id = project_id
        self.log_path = log_path or records_dir() / "powercontext_state_record.jsonl"
        self._stack: AsyncExitStack | None = None
        self._runtime: Any = None
        self._scope_id: str | None = None

    async def __aenter__(self) -> "PowerContextStateStore":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._stack = AsyncExitStack()
        self._runtime = await self._stack.enter_async_context(
            open_builtin_runtime(
                BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{self.db_path.as_posix()}"))
            )
        )
        scope = await self._runtime.scopes.create(
            ScopeDraft(
                title=f"SDD context · {self.project_id}",
                summary="Spec-driven development task state",
                idempotency_key=f"sdd-context:{self.project_id}",
            )
        )
        self._scope_id = scope.scope_id
        self._log("open", {"scope_id": self._scope_id, "db": str(self.db_path)})
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._runtime = None
        self._scope_id = None

    def _memory(self):
        if self._runtime is None or self._scope_id is None:
            raise RuntimeError("PowerContext state store is not open")
        return self._runtime.memory.for_scope(self._scope_id)

    async def save(self, state: TaskState) -> dict[str, Any]:
        if not state.updated_at:
            state.updated_at = datetime.now(UTC).isoformat()
        text = STATE_PREFIX + json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True)
        result = await self._memory().remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=text),))
        )
        entry = result.entry
        record = {
            "task_id": state.task_id,
            "status": state.status,
            "scope_id": self._scope_id,
            "entry_id": entry.entry.entry_id if entry else "",
            "version": entry.entry.version if entry else None,
            "updated_at": state.updated_at,
        }
        self._log("save", record)
        return record

    async def load(self, task_id: str) -> TaskState | None:
        states = await self.load_all()
        matches = [state for state in states if state.task_id == task_id]
        if not matches:
            self._log("load_miss", {"task_id": task_id, "scope_id": self._scope_id})
            return None
        latest = max(matches, key=lambda item: (item.updated_at, item.status))
        self._log("load_hit", {"task_id": task_id, "scope_id": self._scope_id, "updated_at": latest.updated_at})
        return latest

    async def load_all(self) -> list[TaskState]:
        page = await self._memory().list()
        states: list[TaskState] = []
        for record in page.entries:
            text = getattr(getattr(record, "entry", None), "text", "")
            if not isinstance(text, str) or not text.startswith(STATE_PREFIX):
                continue
            try:
                payload = json.loads(text[len(STATE_PREFIX) :])
            except ValueError:
                continue
            if isinstance(payload, dict):
                states.append(TaskState.from_dict(payload))
        return states

    async def entries(self) -> list[dict[str, Any]]:
        page = await self._memory().list()
        out: list[dict[str, Any]] = []
        for record in page.entries:
            entry = getattr(record, "entry", None)
            text = getattr(entry, "text", "")
            out.append(
                {
                    "entry_id": getattr(entry, "entry_id", ""),
                    "kind": getattr(entry, "kind", ""),
                    "version": getattr(entry, "version", None),
                    "text": text,
                }
            )
        return out

    def _log(self, action: str, payload: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "project_id": self.project_id,
            **payload,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
