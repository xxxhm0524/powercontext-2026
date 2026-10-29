# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Capture the original visible events of one selected Pi session branch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    AdapterSourceDefinition,
    Connector,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    Source,
    SourceMaterialization,
    TextEvidence,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"


class PiSessionInput(BaseModel):
    """Bytes of one Pi v3 JSONL session and an optional selected leaf."""

    model_config = ConfigDict(extra="forbid")

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event together with the complete source record."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """Durable captured Source holding one complete Pi event."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_source_identity(self) -> PiEventSource:
        if self.source_id != self.name:
            raise ValueError("Pi event source_id must equal its Source name")  # noqa: TRY003
        return self


class PiEventSourceAdapter:
    """Resolve parsed Pi events into stable Sources and read them back exactly."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        identity = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose the complete event text without the model-facing compaction view."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Return a stable, bounded, collision-safe identity for one session event."""

    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be a non-empty string")  # noqa: TRY003
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be a non-empty string")  # noqa: TRY003
    identity = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        digest = hashlib.sha256(f"{session_id}\0{event_id}".encode()).hexdigest()
        identity = f"pi:{digest}"
    return identity


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse a Pi v3 JSONL file and return the visible events on one branch."""

    try:
        text = value.content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error
    if not text.strip():
        raise ValueError("Pi session content must not be empty")

    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid Pi session JSON on line {number}: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"Pi session line {number} must be a JSON object")
        records.append(record)

    if not records:
        raise ValueError("Pi session content must contain a session header")
    header = records[0]
    if header.get("type") != "session" or header.get("version") != 3:
        raise ValueError("Pi session must start with a version 3 session header")
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Pi session header id must be a non-empty string")

    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records[1:]:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("every Pi session record must have a non-empty string id")
        if event_id in by_id:
            raise ValueError(f"duplicate Pi session record id: {event_id!r}")
        if "parentId" not in record:
            raise ValueError(f"Pi session record {event_id!r} is missing parentId")
        parent_id = record.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise ValueError(f"Pi session record {event_id!r} has an invalid parentId")
            if parent_id not in by_id:
                raise ValueError(f"Pi session record {event_id!r} references an unknown parent")
        by_id[event_id] = record
        order.append(event_id)

    if not order:
        raise ValueError("Pi session must contain at least one record after the header")

    leaf_id = value.leaf_id if value.leaf_id is not None else order[-1]
    if leaf_id not in by_id:
        raise ValueError(f"Pi session leaf {leaf_id!r} does not exist")

    chain: list[str] = []
    current: str | None = leaf_id
    while current is not None:
        if current not in by_id:
            raise ValueError(f"Pi session branch references unknown record {current!r}")
        if current in chain:
            raise ValueError("Pi session contains a parent cycle")
        chain.append(current)
        current = by_id[current].get("parentId")
    chain.reverse()

    events: list[PiEventInput] = []
    for event_id in chain:
        record = by_id[event_id]
        visible = _visible_event(session_id, event_id, record)
        if visible is not None:
            events.append(visible)
    return tuple(events)


class PiSessionConnector(Connector):
    """Incrementally import one selected Pi branch using the durable checkpoint."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        raw = self._path.read_bytes()
        events = parse_pi_session(PiSessionInput(content=raw, leaf_id=self._leaf_id))
        checkpoint = _load_checkpoint(session.checkpoint)
        if events:
            session_id = events[0].session_id
            if checkpoint["session_id"] is None:
                checkpoint["session_id"] = session_id
            elif checkpoint["session_id"] != session_id:
                raise ValueError("Pi session checkpoint belongs to a different session")

        records: dict[str, str] = checkpoint["records"]
        for event in events:
            digest = _record_digest(event.record)
            known = records.get(event.event_id)
            if known is not None and known != digest:
                raise ValueError(f"imported Pi event {event.event_id!r} was modified")
            if known is None:
                await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)

        if checkpoint["session_id"] is None and not events:
            raise ValueError("Pi session must contain at least one visible event")

        next_checkpoint = {
            "version": 1,
            "session_id": checkpoint["session_id"],
            "records": {
                event.event_id: _record_digest(event.record) for event in events
            },
        }
        # Preserve events imported from other branches as historical evidence.
        for event_id, digest in records.items():
            next_checkpoint["records"].setdefault(event_id, digest)
        if next_checkpoint == session.checkpoint:
            return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=session.checkpoint)
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=next_checkpoint)


def _visible_event(session_id: str, event_id: str, record: dict[str, Any]) -> PiEventInput | None:
    event_type = record.get("type")
    parent_id = record.get("parentId")
    if not isinstance(event_type, str):
        return None

    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role:
            return None
        if role == "toolResult":
            body = _tool_result_body(message)
            return _event(session_id, event_id, parent_id, event_type, role, body, record)
        if role == "bashExecution":
            body = _bash_execution_body(message)
            return _event(session_id, event_id, parent_id, event_type, role, body, record)
        body = _message_body(message)
        return _event(session_id, event_id, parent_id, event_type, role, body, record)

    if event_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        if not isinstance(summary, str):
            return None
        return _event(session_id, event_id, parent_id, event_type, event_type, summary, record)

    if event_type == "custom_message":
        body = _text_blocks(record.get("content"))
        return _event(session_id, event_id, parent_id, event_type, "custom", body, record)

    return None


def _event(
    session_id: str,
    event_id: str,
    parent_id: object,
    event_type: str,
    role: str,
    body: str,
    record: dict[str, Any],
) -> PiEventInput | None:
    if not body:
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=event_id,
        parent_id=parent_id if isinstance(parent_id, str) else None,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _message_body(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif block_type == "toolCall":
            name = block.get("name")
            call_id = block.get("id")
            if not isinstance(name, str) or not isinstance(call_id, str):
                continue
            arguments = block.get("arguments")
            parts.append(f"[tool_call {name} {call_id}] {_compact_json(arguments)}")
    return "\n".join(parts)


def _tool_result_body(message: dict[str, Any]) -> str:
    tool_name = message.get("toolName")
    call_id = message.get("toolCallId")
    name = tool_name if isinstance(tool_name, str) else ""
    identity = call_id if isinstance(call_id, str) else ""
    text = _text_blocks(message.get("content"))
    return f"[tool_result {name} {identity}] {text}"


def _bash_execution_body(message: dict[str, Any]) -> str:
    command = message.get("command")
    output = message.get("output")
    command_text = command if isinstance(command, str) else ""
    output_text = output if isinstance(output, str) else ""
    return f"$ {command_text}\n{output_text}"


def _text_blocks(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_digest(record: dict[str, JsonValue]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_checkpoint(value: JsonValue | None) -> dict[str, Any]:
    if value is None:
        return {"session_id": None, "records": {}}
    if not isinstance(value, dict):
        raise ValueError("Pi session checkpoint must be a JSON object")
    version = value.get("version")
    if version != 1:
        raise ValueError("unsupported Pi session checkpoint version")
    session_id = value.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id):
        raise ValueError("Pi session checkpoint has an invalid session id")
    raw_records = value.get("records")
    if not isinstance(raw_records, dict):
        raise ValueError("Pi session checkpoint has invalid records")
    records: dict[str, str] = {}
    for event_id, digest in raw_records.items():
        if not isinstance(event_id, str) or not event_id or not isinstance(digest, str):
            raise ValueError("Pi session checkpoint has invalid event records")
        records[event_id] = digest
    return {"session_id": session_id, "records": records}


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    version="1",
    projections=(PiEventTextEvidenceProjection(),),
)

__all__ = [
    "PI_EVENT_SOURCE_ADAPTER",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiEventSourceAdapter",
    "PiEventTextEvidenceProjection",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
