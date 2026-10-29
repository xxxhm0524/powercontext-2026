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

"""Propagate Source availability through explicit Memory and Topic evidence DAGs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import insert, select, update

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_STATES_TABLE,
    TOPIC_MEMORY_LIFECYCLE_TABLE,
)
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime
    from powercontext.builtin.runtime.relational import RelationalContexts


class SourceLifecycleError(ValueError):
    """Report an invalid lifecycle graph, event, or generation request."""


class SourceLifecycleEvent(BaseModel):
    """One versioned availability change for a registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("lifecycle text must be non-empty and non-blank")  # noqa: TRY003
        return value


class _NodeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: Literal["source", "memory", "topic"]
    ref: dict[str, JsonValue]
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    available: bool = True
    source_revision: int | None = None
    last_sequence: int | None = None
    last_event: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> _NodeState:
        if self.kind == "source":
            if self.source_revision is None or self.parents or self.policy != "all":
                raise ValueError("source lifecycle nodes must declare only their revision")  # noqa: TRY003
        elif self.source_revision is not None:
            raise ValueError("derived lifecycle nodes must not declare a Source revision")  # noqa: TRY003
        return self


class _LifecycleState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: dict[str, _NodeState] = Field(default_factory=dict)

    def available_ids(self) -> list[str]:
        return sorted(node_id for node_id, node in self.nodes.items() if node.available)


class SourceLifecycleApplication:
    """Expose one lifecycle service per Scope on the built-in Runtime."""

    def __init__(self, runtime: BuiltinRuntime, contexts: RelationalContexts) -> None:
        self._runtime = runtime
        self._contexts = contexts

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, self._contexts, validate_scope_id(scope_id))


class ScopedSourceLifecycle:
    """Register the evidence DAG and propagate one Scope's Source availability."""

    def __init__(self, runtime: BuiltinRuntime, contexts: RelationalContexts, scope_id: str) -> None:
        self._runtime = runtime
        self._contexts = contexts
        self.scope_id = scope_id

    async def register_source(self, node_id: str, source_ref: SourceRef, /, *, revision: int) -> None:
        node = _require_node_id(node_id)
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("revision must be a positive integer")
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source_ref must be a SourceRef")
        async with self._runtime._context(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._load()
            existing = state.nodes.get(node)
            if existing is not None:
                if (
                    existing.kind == "source"
                    and existing.ref == source_ref.model_dump(mode="json")
                    and existing.source_revision == revision
                ):
                    return
                raise SourceLifecycleError("node identity is already registered with a different binding")
            await self._require_source(source_ref)
            state.nodes[node] = _NodeState(
                node_id=node,
                kind="source",
                ref=source_ref.model_dump(mode="json"),
                available=True,
                source_revision=revision,
            )
            await self._save(state)

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        node = _require_node_id(node_id)
        _require_policy(policy)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("citation must be a MemoryCitation")
        async with self._runtime._context(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._load()
            parent_ids = self._require_parents(node, parents, state)
            existing = state.nodes.get(node)
            if existing is not None:
                if (
                    existing.kind == "memory"
                    and existing.ref == citation.model_dump(mode="json")
                    and existing.parents == parent_ids
                    and existing.policy == policy
                ):
                    return
                raise SourceLifecycleError("node identity is already registered with a different binding")
            await self._require_memory(citation)
            available = _supports(parent_ids, policy, state)
            record = _NodeState(
                node_id=node,
                kind="memory",
                ref=citation.model_dump(mode="json"),
                parents=parent_ids,
                policy=policy,
                available=available,
            )
            if not available:
                await self._apply_memory_state(record, False)
            state.nodes[node] = record
            await self._save(state)

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        /,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        node = _require_node_id(node_id)
        _require_policy(policy)
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("artifact_ref must reference topic-memory")
        async with self._runtime._context(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._load()
            parent_ids = self._require_parents(node, parents, state)
            existing = state.nodes.get(node)
            if existing is not None:
                if (
                    existing.kind == "topic"
                    and existing.ref == artifact_ref.model_dump(mode="json")
                    and existing.parents == parent_ids
                    and existing.policy == policy
                ):
                    return
                raise SourceLifecycleError("node identity is already registered with a different binding")
            await self._require_topic(artifact_ref)
            available = _supports(parent_ids, policy, state)
            state.nodes[node] = _NodeState(
                node_id=node,
                kind="topic",
                ref=artifact_ref.model_dump(mode="json"),
                parents=parent_ids,
                policy=policy,
                available=available,
            )
            async with self._contexts.database.transaction() as connection:
                await self._write_topic_state(connection, artifact_ref, available)
            await self._save(state)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("apply requires a SourceLifecycleEvent")
        async with self._runtime._context(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._load()
            node = state.nodes.get(event.node_id)
            if node is None or node.kind != "source":
                raise SourceLifecycleError("event must target a registered Source")
            if node.source_revision != event.revision:
                raise SourceLifecycleError("event revision does not match the registered Source revision")
            if node.last_sequence is not None:
                if event.sequence < node.last_sequence:
                    raise SourceLifecycleError("event sequence must increase monotonically")
                if event.sequence == node.last_sequence:
                    if node.last_event == event.model_dump(mode="json"):
                        return state.available_ids()
                    raise SourceLifecycleError("an equal sequence cannot carry a different event")
            node.last_sequence = event.sequence
            node.last_event = event.model_dump(mode="json")
            node.available = event.available

            changed_memory: list[tuple[_NodeState, bool]] = []
            changed_topic: list[tuple[_NodeState, bool]] = []
            for record in state.nodes.values():
                if record.kind == "source":
                    continue
                available = _supports(record.parents, record.policy, state)
                if available == record.available:
                    continue
                record.available = available
                if record.kind == "memory":
                    changed_memory.append((record, available))
                else:
                    changed_topic.append((record, available))

            for record, available in changed_memory:
                await self._apply_memory_state(record, available)

            async with self._contexts.database.transaction() as connection:
                for record, available in changed_topic:
                    await self._write_topic_state(connection, ArtifactRef.model_validate(record.ref), available)
                await self._write_state(connection, state)
            return state.available_ids()

    async def resolve(self, node_id: str, /, *, purpose: str) -> SourceRef | MemoryCitation | ArtifactRef:
        node = _require_node_id(node_id)
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("purpose must be generation or audit")
        state = await self._load()
        record = state.nodes.get(node)
        if record is None:
            raise SourceLifecycleError("unknown lifecycle node")
        if purpose == "generation" and not record.available:
            raise SourceLifecycleError("node is unavailable for generation")
        if record.kind == "source":
            return SourceRef.model_validate(record.ref)
        if record.kind == "memory":
            return MemoryCitation.model_validate(record.ref)
        return ArtifactRef.model_validate(record.ref)

    async def _load(self) -> _LifecycleState:
        async with self._contexts.database.transaction() as connection:
            row = (
                await connection.execute(
                    select(SOURCE_LIFECYCLE_STATES_TABLE.c.state).where(
                        SOURCE_LIFECYCLE_STATES_TABLE.c.scope_id == self.scope_id
                    )
                )
            ).scalar()
        if row is None:
            return _LifecycleState()
        try:
            return _LifecycleState.model_validate_json(row)
        except ValueError as error:
            raise SourceLifecycleError("stored lifecycle state is invalid") from error

    async def _save(self, state: _LifecycleState) -> None:
        async with self._contexts.database.transaction() as connection:
            await self._write_state(connection, state)

    async def _write_state(self, connection, state: _LifecycleState) -> None:
        table = SOURCE_LIFECYCLE_STATES_TABLE
        payload = state.model_dump_json()
        current = await connection.scalar(
            select(table.c.version).where(table.c.scope_id == self.scope_id)
        )
        if current is None:
            await connection.execute(
                insert(table).values(scope_id=self.scope_id, state=payload, version=1)
            )
        else:
            await connection.execute(
                update(table)
                .where(table.c.scope_id == self.scope_id, table.c.version == int(current))
                .values(state=payload, version=int(current) + 1)
            )

    async def _write_topic_state(self, connection, artifact_ref: ArtifactRef, available: bool) -> None:
        table = TOPIC_MEMORY_LIFECYCLE_TABLE
        current = await connection.scalar(
            select(table.c.available).where(
                table.c.scope_id == self.scope_id,
                table.c.artifact_id == artifact_ref.artifact_id,
            )
        )
        if current is None:
            await connection.execute(
                insert(table).values(
                    scope_id=self.scope_id,
                    artifact_id=artifact_ref.artifact_id,
                    available=available,
                )
            )
        elif bool(current) != available:
            await connection.execute(
                update(table)
                .where(
                    table.c.scope_id == self.scope_id,
                    table.c.artifact_id == artifact_ref.artifact_id,
                )
                .values(available=available)
            )

    async def _apply_memory_state(self, record: _NodeState, available: bool) -> None:
        citation = MemoryCitation.model_validate(record.ref)
        context = await self._contexts.get(self.scope_id)
        service = context.artifacts.memory
        current = await service.head(citation.memory_ref.artifact_id)
        manifest = next(
            (item for item in current.content.manifest.entries if item.entry_id == citation.entry_id),
            None,
        )
        if manifest is None:
            raise SourceLifecycleError("registered Memory entry no longer exists")
        desired = "active" if available else "inactive"
        if manifest.state == desired:
            return
        entry = next(
            (item for item in await service.entries(current) if item.entry_id == citation.entry_id),
            None,
        )
        if entry is None:
            raise SourceLifecycleError("registered Memory entry cannot be read")
        if available:
            await service.reactivate(current, entries=(entry,), reason="source lifecycle restore")
        else:
            await service.forget(current, entries=(entry,), reason="source lifecycle withdrawal")

    async def _require_source(self, source_ref: SourceRef) -> None:
        try:
            async with self._contexts.database.transaction() as connection:
                await self._contexts.repositories.sources.get(connection, self.scope_id, source_ref)
        except Exception as error:
            raise SourceLifecycleError("registered Source reference is not readable") from error

    async def _require_memory(self, citation: MemoryCitation) -> None:
        try:
            context = await self._contexts.get(self.scope_id)
            service = context.artifacts.memory
            memory = await service.revision(citation.memory_ref)
            if not any(
                item.entry_id == citation.entry_id and item.entry_version_id == citation.entry_version_id
                for item in memory.content.manifest.entries
            ):
                raise SourceLifecycleError("registered Memory citation is not present")
            await service.validate_citation(citation)
        except SourceLifecycleError:
            raise
        except Exception as error:
            raise SourceLifecycleError("registered Memory citation is not readable") from error

    async def _require_topic(self, artifact_ref: ArtifactRef) -> None:
        try:
            async with self._contexts.database.transaction() as connection:
                await self._contexts.repositories.artifacts.get(connection, self.scope_id, artifact_ref)
        except Exception as error:
            raise SourceLifecycleError("registered Topic reference is not readable") from error

    def _require_parents(
        self, node_id: str, parents: tuple[str, ...], state: _LifecycleState
    ) -> tuple[str, ...]:
        if not isinstance(parents, tuple) or not parents:
            raise SourceLifecycleError("derived nodes require at least one parent")
        ordered: list[str] = []
        seen: set[str] = set()
        for parent in parents:
            _require_node_id(parent)
            if parent == node_id:
                raise SourceLifecycleError("a lifecycle node cannot depend on itself")
            if parent in seen:
                raise SourceLifecycleError("parent nodes must be unique")
            if parent not in state.nodes:
                raise SourceLifecycleError("parent nodes must be registered first")
            seen.add(parent)
            ordered.append(parent)
        return tuple(ordered)


def _require_node_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError("node_id must be a non-empty string")
    return value


def _require_policy(value: str) -> None:
    if value not in {"all", "any"}:
        raise SourceLifecycleError("policy must be 'all' or 'any'")


def _supports(parents: tuple[str, ...], policy: Literal["all", "any"], state: _LifecycleState) -> bool:
    support = tuple(state.nodes[parent].available for parent in parents)
    return all(support) if policy == "all" else any(support)


__all__ = ["ScopedSourceLifecycle", "SourceLifecycleApplication", "SourceLifecycleError", "SourceLifecycleEvent"]
