"""End-to-end smoke test for the Memory Tavern backend (no Dify required).

Run from this directory:

    python smoke_test.py

It starts the FastAPI lifespan (which opens a real embedded PowerContext
runtime with SQLite), simulates two separate conversations for the same player,
and verifies that a fact told in the first conversation is recalled in the
second one.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MEMORY_TAVERN_DATA", tempfile.mkdtemp(prefix="memory-tavern-smoke-"))

import httpx  # noqa: E402

from app import app  # noqa: E402


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://memory-tavern") as client:
            first = await client.post(
                "/remember",
                json={
                    "player_id": "smoke-player",
                    "user_message": "我叫阿岚，我最喜欢桂花酿，还欠你一枚铜币。",
                    "assistant_reply": "阿岚，桂花酿给你留着，铜币的事我也记着。",
                },
            )
            first.raise_for_status()

            recall = await client.post(
                "/recall",
                json={"player_id": "smoke-player", "query": "我叫什么名字？我欠你什么？"},
            )
            recall.raise_for_status()
            context = recall.text
            print(context)
            assert "阿岚" in context
            assert "铜币" in context
            print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
