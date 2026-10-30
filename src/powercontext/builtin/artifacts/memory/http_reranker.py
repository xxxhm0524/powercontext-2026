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

"""HTTP cross-encoder adapter implementing the MemoryReranker contract."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


class HTTPMemoryReranker:
    """Score candidates through one HTTP endpoint, in bounded batches.

    The endpoint receives global one-based candidate ranks and must answer with
    scores for exactly those ranks. Selections are made across the complete
    candidate pool so a strong later batch can outrank an early one.
    """

    policy_id = "http-cross-encoder-v1"

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint:
            raise ValueError("endpoint must be a non-empty string")  # noqa: TRY003
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        if not isinstance(query, str) or not query:
            raise ValueError("query must be a non-empty string")  # noqa: TRY003
        if len(candidates) < 1:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if type(limit) is not int or limit < 1 or limit > len(candidates):
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

        ranked = tuple(enumerate(candidates, start=1))
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(ranked), self._batch_size):
            batch = ranked[start : start + self._batch_size]
            payload = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": hit.text}
                    for rank, hit in batch
                ],
            }
            response = await self._client.post(self._endpoint, json=payload)
            requests += 1
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError as error:
                raise ValueError("reranker response is not valid JSON") from error
            batch_scores = _parse_scores(body, expected_ranks={rank for rank, _ in batch})
            scores.update(batch_scores)

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for rank, _ in ordered[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _parse_scores(body: object, *, expected_ranks: set[int]) -> dict[int, float]:
    if not isinstance(body, dict) or set(body) != {"scores"}:
        raise ValueError("reranker response must contain exactly 'scores'")  # noqa: TRY003
    raw_scores = body["scores"]
    if not isinstance(raw_scores, list):
        raise ValueError("reranker scores must be a list")  # noqa: TRY003
    scores: dict[int, float] = {}
    for item in raw_scores:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            raise ValueError("each reranker score must contain exactly rank and score")  # noqa: TRY003
        rank = item["rank"]
        score = item["score"]
        if type(rank) is not int:
            raise ValueError("reranker rank must be an integer")  # noqa: TRY003
        if type(score) not in (int, float):
            raise ValueError("reranker score must be numeric")  # noqa: TRY003
        numeric_score = float(score)
        if not math.isfinite(numeric_score):
            raise ValueError("reranker score must be finite")  # noqa: TRY003
        if rank in scores:
            raise ValueError("reranker rank must not repeat")  # noqa: TRY003
        scores[rank] = numeric_score
    if set(scores) != expected_ranks:
        raise ValueError("reranker scores must cover exactly the requested ranks")  # noqa: TRY003
    return scores


__all__ = ["HTTPMemoryReranker"]
