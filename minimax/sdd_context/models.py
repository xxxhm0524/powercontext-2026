"""Small, serialisable models shared by the CLI, selector and validator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit of engineering material."""

    chunk_id: str
    kind: str  # spec | code | test
    source_path: str
    symbol: str
    title: str
    content: str
    start_line: int
    end_line: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectedSource:
    kind: str
    source_path: str
    symbol: str
    title: str
    start_line: int
    end_line: int
    score: float
    reasons: list[str] = field(default_factory=list)
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskState:
    """Task progress persisted through PowerContext."""

    task_id: str
    status: str = "new"
    completed: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskState":
        return cls(
            task_id=str(payload.get("task_id", "")),
            status=str(payload.get("status", "new")),
            completed=[str(item) for item in payload.get("completed", [])],
            todo=[str(item) for item in payload.get("todo", [])],
            verification=dict(payload.get("verification", {})),
            notes=str(payload.get("notes", "")),
            updated_at=str(payload.get("updated_at", "")),
        )


@dataclass
class ContextBundle:
    task_id: str
    query: str
    project_root: str
    generated_at: str
    specs: list[SelectedSource] = field(default_factory=list)
    code: list[SelectedSource] = field(default_factory=list)
    tests: list[SelectedSource] = field(default_factory=list)
    state: TaskState | None = None
    sources: list[SelectedSource] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "project_root": self.project_root,
            "generated_at": self.generated_at,
            "specs": [item.to_dict() for item in self.specs],
            "code": [item.to_dict() for item in self.code],
            "tests": [item.to_dict() for item in self.tests],
            "state": self.state.to_dict() if self.state else None,
            "sources": [item.to_dict() for item in self.sources],
            "stats": self.stats,
        }

    def required_source_keys(self) -> list[tuple[str, str, str]]:
        """Return stable identities used by the validator."""

        keys: list[tuple[str, str, str]] = []
        for item in self.sources:
            keys.append((item.kind, item.source_path, item.symbol))
        return keys
