"""Optional HTTP entry point for the SDD context module.

The CLI is the primary documented interface; this FastAPI adapter is useful for
agent plugins and for reviewers who prefer a service call::

    uvicorn scripts.http_server:app --host 127.0.0.1 --port 8765
    curl -X POST http://127.0.0.1:8765/context -H 'Content-Type: application/json' \
         -d '{"task_id":"TASK-1","query":"为订单列表增加按状态和最低金额筛选"}'
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdd_context.config import ensure_runtime_dirs, project_root as default_root
from sdd_context.models import TaskState
from sdd_context.seekdb_store import SeekDBMaterialStore, default_query_log
from sdd_context.selector import select_context
from sdd_context.state import PowerContextStateStore

ensure_runtime_dirs()
app = FastAPI(title="SDD Context Module", version="1.0.0")


class ContextRequest(BaseModel):
    task_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    project_root: str | None = None
    include_state: bool = True


class StateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    status: str = "new"
    completed: list[str] = Field(default_factory=list)
    todo: list[str] = Field(default_factory=list)
    verification: dict = Field(default_factory=dict)
    notes: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/context")
def context(request: ContextRequest) -> dict:
    root = Path(request.project_root).resolve() if request.project_root else default_root()
    state = None
    if request.include_state:
        async def _load() -> TaskState | None:
            async with PowerContextStateStore(project_id="sdd-order-demo") as store:
                return await store.load(request.task_id)
        state = asyncio.run(_load())
    with SeekDBMaterialStore(query_log=default_query_log()) as store:
        bundle = select_context(store, task_id=request.task_id, query=request.query, project_root=root, state=state)
    return bundle.to_dict()


@app.get("/state/{task_id}")
def get_state(task_id: str) -> dict:
    async def _load() -> dict:
        async with PowerContextStateStore(project_id="sdd-order-demo") as store:
            state = await store.load(task_id)
            return {"state": state.to_dict() if state else None}
    return asyncio.run(_load())


@app.post("/state")
def save_state(request: StateRequest) -> dict:
    async def _save() -> dict:
        async with PowerContextStateStore(project_id="sdd-order-demo") as store:
            current = await store.load(request.task_id) or TaskState(task_id=request.task_id)
            current.status = request.status
            for item in request.completed:
                if item not in current.completed:
                    current.completed.append(item)
            current.todo = list(request.todo)
            current.verification = dict(request.verification)
            current.notes = request.notes
            return await store.save(current)
    return asyncio.run(_save())
