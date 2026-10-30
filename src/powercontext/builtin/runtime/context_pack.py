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

"""Versioned context packs and prefix-reuse deltas."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512


class ContextPackError(ValueError):
    """Report an invalid context pack, delta, or chunk boundary."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list):
        raise ContextPackError("items must be a list")
    decoded: list[bytes] = []
    for value in values:
        if not isinstance(value, str):
            raise ContextPackError("each item must be a Base64 string")
        try:
            decoded.append(base64.b64decode(value.encode("ascii"), validate=True))
        except (UnicodeEncodeError, binascii.Error) as error:
            raise ContextPackError("item is not valid Base64") from error
    return tuple(decoded)


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": PACK_SCHEMA, "items": _encode_items(items)}
    return "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()


def _render_pack(items: tuple[bytes, ...], digest: str, byte_count: int) -> bytes:
    return _canonical(
        {
            "schema": PACK_SCHEMA,
            "items": _encode_items(items),
            "digest": digest,
            "byte_count": byte_count,
        }
    )


def _solve_byte_count(render) -> int:
    candidate = 0
    for _ in range(8):
        data = render(candidate)
        if len(data) == candidate:
            return candidate
        candidate = len(data)
    raise ContextPackError("byte_count did not converge")


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete context represented as an ordered tuple of byte chunks."""

    items: tuple[bytes, ...]
    digest: str

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        normalized: list[bytes] = []
        for item in items:
            if not isinstance(item, (bytes, bytearray)):
                raise ContextPackError("each context item must be bytes")
            normalized.append(bytes(item))
        packed = tuple(normalized)
        return cls(items=packed, digest=_pack_digest(packed))

    @classmethod
    def from_content(cls, content: str | bytes, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if isinstance(content, str):
            text = content
        elif isinstance(content, (bytes, bytearray)):
            try:
                text = bytes(content).decode("utf-8")
            except UnicodeDecodeError as error:
                raise ContextPackError("content must be valid UTF-8") from error
        else:
            raise ContextPackError("content must be text or bytes")
        chunks: list[bytes] = []
        buffer: list[str] = []
        size = 0
        for character in text:
            encoded = character.encode("utf-8")
            if len(encoded) > chunk_bytes:
                raise ContextPackError("a single character exceeds the chunk budget")
            if size + len(encoded) > chunk_bytes:
                chunks.append("".join(buffer).encode("utf-8"))
                buffer = []
                size = 0
            buffer.append(character)
            size += len(encoded)
        if buffer:
            chunks.append("".join(buffer).encode("utf-8"))
        return cls.build(tuple(chunks))

    def to_bytes(self) -> bytes:
        return _render_pack(
            self.items,
            self.digest,
            _solve_byte_count(lambda count: _render_pack(self.items, self.digest, count)),
        )

    @property
    def byte_count(self) -> int:
        return _solve_byte_count(lambda count: _render_pack(self.items, self.digest, count))

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> ContextPack:
        try:
            payload = json.loads(bytes(data).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContextPackError("pack is not valid UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise ContextPackError("pack must be a JSON object")
        if set(payload) != {"schema", "items", "digest", "byte_count"}:
            raise ContextPackError("pack fields do not match the wire schema")
        if payload["schema"] != PACK_SCHEMA:
            raise ContextPackError("unsupported context pack schema")
        items = _decode_items(payload["items"])
        digest = payload["digest"]
        if not isinstance(digest, str) or digest != _pack_digest(items):
            raise ContextPackError("context pack digest does not match its items")
        byte_count = payload["byte_count"]
        if type(byte_count) is not int or byte_count != len(bytes(data)):
            raise ContextPackError("context pack byte_count does not match its encoding")
        return cls(items=items, digest=digest)


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A prefix-reuse delta from one complete pack to another."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta operands must be ContextPack values")
        prefix = 0
        limit = min(len(base.items), len(target.items))
        while prefix < limit and base.items[prefix] == target.items[prefix]:
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    def to_bytes(self) -> bytes:
        return _canonical(
            {
                "schema": DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": _encode_items(self.appended),
            }
        )

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> ContextPackDelta:
        try:
            payload = json.loads(bytes(data).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContextPackError("delta is not valid UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise ContextPackError("delta must be a JSON object")
        if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
            raise ContextPackError("delta fields do not match the wire schema")
        if payload["schema"] != DELTA_SCHEMA:
            raise ContextPackError("unsupported context pack delta schema")
        base_digest = payload["base_digest"]
        target_digest = payload["target_digest"]
        if not isinstance(base_digest, str) or not base_digest.startswith("sha256:"):
            raise ContextPackError("invalid base digest")
        if not isinstance(target_digest, str) or not target_digest.startswith("sha256:"):
            raise ContextPackError("invalid target digest")
        prefix = payload["prefix_items"]
        if type(prefix) is not int or prefix < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        appended = _decode_items(payload["appended"])
        return cls(
            base_digest=base_digest,
            target_digest=target_digest,
            prefix_items=prefix,
            appended=appended,
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild the target pack from a base and one delta."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("apply requires a ContextPack and a ContextPackDelta")
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the supplied base")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix exceeds the base chunk count")
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match the rebuilt pack")
    return target


__all__ = [
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
