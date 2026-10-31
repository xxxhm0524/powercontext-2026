"""Memory Tavern backend: a thin, reproducible PowerContext adapter for Dify.

Dify owns the conversation flow.  This service owns the long-term memory:

* ``POST /recall``   -> a plain-text "guest book" assembled from PowerContext
* ``POST /remember`` -> append one finished exchange as a Memory entry
* ``GET  /stats/{player_id}`` -> inspection endpoint used by the validation guide
* ``GET  /health``   -> readiness probe

Both endpoints accept JSON and form-data.  The bundled Dify DSL uses form-data
so user text containing quotes or line breaks can never corrupt a JSON request.

PowerContext itself persists the memories in SQLite (``data/memory_tavern.db``),
which is an officially supported built-in runtime of the pinned v1.2.0 release.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft

logger = logging.getLogger("memory_tavern")

DATA_DIR = Path(os.environ.get("MEMORY_TAVERN_DATA", Path(__file__).parent / "data"))
DATABASE_PATH = DATA_DIR / "memory_tavern.db"
RECALL_LIMIT = int(os.environ.get("MEMORY_TAVERN_RECALL_LIMIT", "12"))
MAX_ENTRY_CHARS = int(os.environ.get("MEMORY_TAVERN_ENTRY_CHARS", "800"))
MAX_CONTEXT_CHARS = int(os.environ.get("MEMORY_TAVERN_CONTEXT_CHARS", "6000"))

_state: dict[str, object] = {}

_CJK = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_NAME_PATTERNS = (
    re.compile(rf"我叫(?!什么|啥|谁|哪)([{_CJK}A-Za-z·]{{1,8}})"),
    re.compile(rf"我的名字(?:是|叫)([{_CJK}A-Za-z·]{{1,8}})"),
    re.compile(rf"叫我([{_CJK}A-Za-z·]{{1,8}})"),
)
_DRINK_PATTERNS = (
    re.compile(
        rf"(?:最喜欢|最爱|很喜欢|喜欢|爱喝|常喝|只喝)(?:喝|吃)?"
        rf"([{_CJK}A-Za-z0-9]{{1,8}}(?:酿|酒|茶|汤|咖啡|果汁|汽水|奶茶))"
    ),
    re.compile(rf"(?:来|要|喝)(?:一|两|三)?(?:杯|壶|碗)?([{_CJK}A-Za-z0-9]{{1,6}}(?:酿|酒|茶|汤))"),
)


class RecallRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=128)
    query: str = Field(default="", max_length=8000)

    @field_validator("player_id")
    @classmethod
    def _clean_player_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("player_id must not be blank")
        return value


class RememberRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=128)
    user_message: str = Field(min_length=1, max_length=8000)
    assistant_reply: str = Field(min_length=1, max_length=8000)

    @field_validator("player_id", "user_message", "assistant_reply")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be blank")
        return value


ModelT = TypeVar("ModelT", bound=BaseModel)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=os.environ.get("MEMORY_TAVERN_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
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
        logger.info("memory tavern ready: database=%s", DATABASE_PATH)
        try:
            yield
        finally:
            logger.info("memory tavern shutting down")
            _state.clear()


app = FastAPI(
    title="Memory Tavern Backend",
    version="1.1.0",
    description="PowerContext v1.2.0 long-term memory adapter for the Dify Memory Tavern app.",
    lifespan=lifespan,
)


def _runtime():
    runtime = _state.get("runtime")
    if runtime is None:
        raise RuntimeError("PowerContext runtime is not ready")
    return runtime


async def _scope_for(player_id: str) -> str:
    """Return the stable PowerContext scope for one Dify user.

    The deterministic idempotency key makes the scope survive backend restarts:
    PowerContext returns the existing scope when the same key and same draft are
    presented again.  The key is hashed so arbitrarily long Dify user ids stay
    within PowerContext's key limit.
    """

    scopes: dict[str, str] = _state["scopes"]  # type: ignore[assignment]
    cached = scopes.get(player_id)
    if cached is not None:
        return cached
    runtime = _runtime()
    digest = hashlib.sha256(player_id.encode("utf-8")).hexdigest()[:32]
    scope = await runtime.scopes.create(
        ScopeDraft(
            title=f"Memory Tavern · {player_id[:64]}",
            summary="Cross-session role-play memories for one tavern guest",
            idempotency_key=f"memory-tavern:{digest}",
        )
    )
    scopes[player_id] = scope.scope_id
    return scope.scope_id


def _entry_text(record) -> str:
    text = getattr(getattr(record, "entry", None), "text", "")
    return text if isinstance(text, str) else ""


def _extract_profile(texts: list[str]) -> dict[str, str]:
    """Pull a few stable guest-book facts out of the remembered turns.

    PowerContext still stores and returns the complete original turns; this
    profile is only a readability aid for the prompt.  It intentionally only
    reports facts that appear verbatim in the memories.
    """

    joined = "\n".join(texts)
    profile: dict[str, str] = {}
    for pattern in _NAME_PATTERNS:
        match = pattern.search(joined)
        if match:
            profile["name"] = match.group(1)
            break
    for pattern in _DRINK_PATTERNS:
        match = pattern.search(joined)
        if match:
            profile["drink"] = match.group(1)
            break
    return profile


def _shorten(text: str, limit: int) -> str:
    cleaned = re.sub(r"[ \t]+", " ", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(1, limit - 1)].rstrip() + "…"


async def _recall_context(player_id: str, query: str) -> str:
    runtime = _runtime()
    scope_id = await _scope_for(player_id)
    memory = runtime.memory.for_scope(scope_id)

    fts_texts: list[str] = []
    if query.strip():
        try:
            page = await memory.search(
                SearchMemoryRequest(query=query, mode="fts", limit=RECALL_LIMIT)
            )
            for hit in page.hits:
                text = getattr(hit, "text", "")
                if isinstance(text, str) and text.strip():
                    fts_texts.append(text)
        except Exception:  # noqa: BLE001 - the recent list is a safe fallback
            logger.warning("FTS recall failed; falling back to recent memories", exc_info=True)

    page = await memory.list()
    records = list(page.entries)
    all_texts = [_entry_text(record) for record in records if _entry_text(record)]

    # FTS hits first (most relevant), then the newest turns that were not
    # already covered by the search.
    ordered: list[str] = []
    seen: set[str] = set()
    for text in fts_texts:
        if text not in seen:
            seen.add(text)
            ordered.append(text)
    for text in reversed(all_texts):
        if text not in seen:
            seen.add(text)
            ordered.append(text)
        if len(ordered) >= RECALL_LIMIT:
            break

    if not ordered:
        return (
            "【常客簿】还是空的。这是你们第一次见面。\n"
            "请热情地招呼这位旅人，问问他的名字，再问他想喝点什么。"
        )

    profile = _extract_profile(all_texts)
    header = ["【常客簿】"]
    if profile:
        if "name" in profile:
            header.append(f"姓名：{profile['name']}")
        if "drink" in profile:
            header.append(f"最爱的酒：{profile['drink']}")
        if "tab" in profile:
            header.append(f"还欠着：{profile['tab']}")
    else:
        header.append("还没有写下名字，但你们已经聊过几次。")

    body: list[str] = []
    used = 0
    for text in ordered[:RECALL_LIMIT]:
        snippet = _shorten(text, MAX_ENTRY_CHARS)
        if used + len(snippet) > MAX_CONTEXT_CHARS:
            body.append("（更早的回忆先留在了酒窖里。）")
            break
        used += len(snippet)
        body.append(f"- {snippet}")

    return "\n".join(header + ["", "【记忆片段】", *body])


async def _request_payload(request: Request) -> dict[str, str]:
    """Accept JSON and both HTML form encodings from Dify or curl."""

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == "application/json":
        try:
            data = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="请求体不是合法 JSON。") from exc
    elif content_type in {"multipart/form-data", "application/x-www-form-urlencoded"}:
        form = await request.form()
        data = {key: value for key, value in form.items() if isinstance(value, str)}
    else:
        raise HTTPException(
            status_code=415,
            detail="请使用 application/json 或 multipart/form-data 提交请求。",
        )
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="请求体必须是对象。")
    return data


def _validated(model: type[ModelT], payload: dict[str, str]) -> ModelT:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "powercontext": "ready", "database": str(DATABASE_PATH)}


@app.post("/recall", response_class=PlainTextResponse)
async def recall(request: Request) -> str:
    payload = await _request_payload(request)
    body = _validated(RecallRequest, payload)
    context = await _recall_context(body.player_id, body.query)
    logger.info(
        "recall player=%s query_chars=%d context_chars=%d",
        body.player_id,
        len(body.query),
        len(context),
    )
    return context


@app.post("/remember")
async def remember(request: Request) -> dict[str, str]:
    payload = await _request_payload(request)
    body = _validated(RememberRequest, payload)
    runtime = _runtime()
    scope_id = await _scope_for(body.player_id)
    memory = runtime.memory.for_scope(scope_id)
    text = f"玩家说：{body.user_message}\n掌柜回应：{body.assistant_reply}"
    result = await memory.remember(
        RememberMemoryRequest(entries=(MemoryEntryInput(kind="episode", text=text),))
    )
    citation = result.entry.citation if result.entry is not None else None
    logger.info(
        "remember player=%s user_chars=%d reply_chars=%d entry=%s",
        body.player_id,
        len(body.user_message),
        len(body.assistant_reply),
        citation.entry_id if citation else "",
    )
    return {
        "status": "saved",
        "entry_id": citation.entry_id if citation else "",
        "memory_artifact_id": citation.memory_ref.artifact_id if citation else "",
    }


@app.get("/stats/{player_id}")
async def stats(player_id: str) -> dict[str, object]:
    """Read back what PowerContext actually stored for one player."""

    cleaned = player_id.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="player_id must not be blank")
    runtime = _runtime()
    scope_id = await _scope_for(cleaned)
    page = await runtime.memory.for_scope(scope_id).list()
    entries = [
        {"entry_id": record.entry.entry_id, "text": _entry_text(record)[:240]}
        for record in page.entries[-5:]
    ]
    return {
        "player_id": cleaned,
        "scope_id": scope_id,
        "memory_count": len(page.entries),
        "latest_entries": entries,
    }
