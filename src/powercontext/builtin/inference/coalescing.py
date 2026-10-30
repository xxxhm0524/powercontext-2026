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

"""Cross-call embedding request coalescing with a bounded success cache."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(slots=True)
class _Pending:
    text: str
    future: asyncio.Future[EmbeddingVector]
    batch: _Batch | None = None


@dataclass(slots=True)
class _Batch:
    usage: InferenceUsage


class CoalescingEmbeddingModel:
    """Merge concurrent identical texts and cache successful vectors."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if isinstance(coalesce_ms, bool) or not isinstance(coalesce_ms, (int, float)) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        self._base = model
        self.profile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, _Pending] = {}
        self._pending: list[_Pending] = []
        self._wake = asyncio.Event()
        self._dispatcher: asyncio.Task[None] | None = None

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        requested = tuple(texts)
        if not requested:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))
        if any(not isinstance(text, str) for text in requested):
            raise ValueError("embedding inputs must be strings")  # noqa: TRY003

        unique: list[str] = []
        seen: set[str] = set()
        for text in requested:
            if text not in seen:
                seen.add(text)
                unique.append(text)

        vectors: dict[str, EmbeddingVector] = {}
        waited: list[_Pending] = []
        for text in unique:
            if self._cache_size > 0 and text in self._cache:
                vectors[text] = self._cache[text]
                self._cache.move_to_end(text)
                continue
            pending = self._inflight.get(text)
            if pending is None:
                pending = _Pending(text=text, future=asyncio.get_running_loop().create_future())
                self._inflight[text] = pending
                self._pending.append(pending)
                self._ensure_dispatcher()
                self._wake.set()
            waited.append(pending)

        for pending in waited:
            vectors[pending.text] = await asyncio.shield(pending.future)

        usage = _sum_usage(pending.batch for pending in waited if pending.batch is not None)
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in requested),
            usage=usage,
        )

    def _ensure_dispatcher(self) -> None:
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.create_task(self._dispatch_loop())

    async def _dispatch_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            if self._coalesce_seconds:
                await asyncio.sleep(self._coalesce_seconds)
            while self._pending:
                batch = self._pending[: self._max_batch_size]
                del self._pending[: len(batch)]
                await self._run_batch(batch)

    async def _run_batch(self, pending: list[_Pending]) -> None:
        texts = tuple(item.text for item in pending)
        batch: _Batch | None = None
        try:
            result = await self._base.embed(texts)
            if len(result.vectors) != len(texts):
                raise ValueError("embedding model returned the wrong vector count")  # noqa: TRY003
            batch = _Batch(usage=result.usage)
            for item, vector in zip(pending, result.vectors, strict=True):
                item.batch = batch
                if self._cache_size > 0:
                    self._cache[item.text] = vector
                    self._cache.move_to_end(item.text)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
            for item, vector in zip(pending, result.vectors, strict=True):
                if not item.future.done():
                    item.future.set_result(vector)
        except Exception as error:
            for item in pending:
                if not item.future.done():
                    item.future.set_exception(error)
        finally:
            for item in pending:
                if self._inflight.get(item.text) is item:
                    del self._inflight[item.text]


def _sum_usage(batches) -> InferenceUsage:
    distinct: list[_Batch] = []
    seen: set[int] = set()
    for batch in batches:
        marker = id(batch)
        if marker not in seen:
            seen.add(marker)
            distinct.append(batch)
    requests = sum(batch.usage.requests for batch in distinct)
    input_values = [batch.usage.input_tokens for batch in distinct if batch.usage.input_tokens is not None]
    output_values = [batch.usage.output_tokens for batch in distinct if batch.usage.output_tokens is not None]
    return InferenceUsage(
        requests=requests,
        input_tokens=sum(input_values) if input_values else None,
        output_tokens=sum(output_values) if output_values else None,
    )


__all__ = ["CoalescingEmbeddingModel"]
