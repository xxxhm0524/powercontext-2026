"""Memory Tavern backend: a thin, reproducible PowerContext adapter for Dify.

The Dify application only needs two HTTP operations:

* ``POST /recall``   -> plain-text memory context for the current player
* ``POST /remember`` -> persist the finished exchange as one Memory entry

PowerContext is the durable memory service; Dify owns the conversation flow,
prompting, and answer presentation.
"""

from __future__ import annotations

import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft

DATA_DIR = Path(os.environ.get("MEMORY_TAVERN_DATA", Path(__file__).parent / "data"))
DATABASE_PATH = DATA_DIR / "memory_tavern.db"
RECALL_LIMIT = int(os.environ.get("MEMORY_TAVERN_RECALL_LIMIT", "12"))

_state: dict[str, object] = {}


class RecallRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=200)
    query: str = Field(default="", max_length=4000)


class RememberRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=200)
    user_message: str = Field(min_length=1, max_length=8000)
    assistant_reply: str = Field(min_length=1, max_length=8000)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with AsyncExitStack() as stack:
        runtime = await stack.enter_async_context(
            open_builtin_runtime(
                BuiltinConfig(
                    database=SQLiteConfig(url=f"sqlite+aiosqlite:///{DATABASE_PATH}"),
                )
            )
        )
        _state["runtime"] = runtime
        _state["scopes"] = {}
        try:
            yield
        finally:
            _state.clear()


app = FastAPI(title="Memory Tavern Backend", version="1.0.0", lifespan=lifespan)


def _runtime():
    runtime = _state.get("runtime")
    if runtime is None:
        raise RuntimeError("runtime is not ready")
    return runtime


async def _scope_for(player_id: str) -> str:
    scopes: dict[str, str] = _state["scopes"]  # type: ignore[assignment]
    cached = scopes.get(player_id)
    if cached is not None:
        return cached
    runtime = _runtime()
    scope = await runtime.scopes.create(
        ScopeDraft(
            title=f"Memory Tavern · {player_id}",
            summary="Cross-session role-play memories",
            idempotency_key=f"memory-tavern:{player_id}",
        )
    )
    scopes[player_id] = scope.scope_id
    return scope.scope_id


def _entry_text(entry) -> str:
    return entry.entry.text if hasattr(entry, "entry") else str(entry)


async def _recall_text(player_id: str, query: str) -> str:
    runtime = _runtime()
    scope_id = await _scope_for(player_id)
    memory = runtime.memory.for_scope(scope_id)

    texts: list[str] = []
    seen: set[str] = set()

    if query.strip():
        try:
            page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=RECALL_LIMIT))
            for hit in page.hits:
                text = getattr(hit, "text", "")
                if text and text not in seen:
                    seen.add(text)
                    texts.append(text)
        except Exception:
            # A FTS-only deployment should still fall back to the recent list.
            pass

    page = await memory.list()
    for entry in page.entries:
        text = _entry_text(entry)
        if text and text not in seen:
            seen.add(text)
            texts.append(text)
        if len(texts) >= RECALL_LIMIT:
            break

    if not texts:
        return "（还没有关于这位玩家的记忆。这是你们第一次见面。）"
    return "\n".join(f"- {text}" for text in texts[-RECALL_LIMIT:])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/recall", response_class=PlainTextResponse)
async def recall(request: RecallRequest) -> str:
    return await _recall_text(request.player_id, request.query)


@app.post("/remember")
async def remember(request: RememberRequest) -> dict[str, str]:
    runtime = _runtime()
    scope_id = await _scope_for(request.player_id)
    memory = runtime.memory.for_scope(scope_id)
    text = (
        f"玩家说：{request.user_message.strip()}\n"
        f"掌柜回应：{request.assistant_reply.strip()}"
    )
    result = await memory.remember(
        RememberMemoryRequest(entries=(MemoryEntryInput(kind="episode", text=text),))
    )
    citation = result.entry.citation if result.entry is not None else None
    return {
        "status": "saved",
        "entry_id": citation.entry_id if citation else "",
        "memory_artifact_id": citation.memory_ref.artifact_id if citation else "",
    }


@app.post("/reset")
async def reset(request: RecallRequest) -> dict[str, str]:
    """Start a fresh story for a new demo player id (keeps old scopes intact)."""

    return {"status": "ok", "message": "使用新的 player_id 即可获得全新的记忆空间。"}
