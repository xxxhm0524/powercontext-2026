"""End-to-end smoke test for the Memory Tavern backend (no Dify required).

Run from this directory:

    python smoke_test.py

The test opens a real embedded PowerContext runtime (SQLite persistence), then
checks the complete memory loop:

1. a brand-new player gets the first-visit fallback;
2. a finished turn is written through ``/remember``;
3. a later ``/recall`` returns the remembered name and drink;
4. a second player is isolated;
5. the same player still recalls the facts after a full runtime restart;
6. form-data input (the protocol used by the Dify DSL) works with quotes and
   line breaks, not just JSON.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

os.environ.setdefault("MEMORY_TAVERN_DATA", tempfile.mkdtemp(prefix="memory-tavern-smoke-"))

import httpx  # noqa: E402

from app import app  # noqa: E402


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://memory-tavern")


async def _remember(client: httpx.AsyncClient, player: str, user: str, reply: str) -> None:
    response = await client.post(
        "/remember",
        data={"player_id": player, "user_message": user, "assistant_reply": reply},
    )
    response.raise_for_status()
    payload = response.json()
    assert payload["status"] == "saved", payload
    assert payload["entry_id"], payload


async def main() -> None:
    async with app.router.lifespan_context(app):
        async with await _client() as client:
            health = await client.get("/health")
            health.raise_for_status()
            assert health.json()["status"] == "ok", health.text

            empty = await client.post(
                "/recall",
                data={"player_id": "smoke-player", "query": "我叫什么名字？"},
            )
            empty.raise_for_status()
            assert "第一次见面" in empty.text, empty.text

            await _remember(
                client,
                "smoke-player",
                "我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。",
                "阿岚，桂花酿给你留着，铜币的事我也记着。",
            )
            await _remember(
                client,
                "smoke-player",
                "给我讲讲雾港的故事吧，我想在那里找一条船。",
                "雾港的船都藏在雾里，等风停了才肯露面。",
            )

            recall = await client.post(
                "/recall",
                json={
                    "player_id": "smoke-player",
                    "query": "掌柜的，还记得我吗？我叫什么名字？我最喜欢喝什么？",
                },
            )
            recall.raise_for_status()
            context = recall.text
            print(context)
            for expected in ("阿岚", "桂花酿", "常客簿", "记忆片段"):
                assert expected in context, f"missing {expected!r} in recall:\n{context}"

            other = await client.post(
                "/recall",
                data={"player_id": "another-player", "query": "我叫什么名字？"},
            )
            other.raise_for_status()
            assert "第一次见面" in other.text, other.text

            stats = await client.get("/stats/smoke-player")
            stats.raise_for_status()
            assert stats.json()["memory_count"] == 2, stats.text

            # Exactly what the bundled Dify DSL sends: multipart/form-data.
            multipart = await client.post(
                "/recall",
                files={
                    "player_id": (None, "smoke-player"),
                    "query": (None, "我最喜欢喝什么？"),
                },
            )
            multipart.raise_for_status()
            assert "桂花酿" in multipart.text, multipart.text

            # Quotes and line breaks are exactly the shapes that break hand-built
            # JSON interpolation; form-data keeps them intact end-to-end.
            await _remember(
                client,
                "smoke-player",
                '掌柜的，我今天带着"小满"一起来，\n她问我：这里有桂花酿吗？',
                '有。给"小满"也温一壶，今晚雨大，慢慢喝。',
            )
            after_special = await client.post(
                "/recall",
                data={"player_id": "smoke-player", "query": "小满想喝什么？"},
            )
            after_special.raise_for_status()
            assert "小满" in after_special.text, after_special.text

            malformed = await client.post(
                "/recall",
                content=b"{not-json",
                headers={"Content-Type": "application/json"},
            )
            assert malformed.status_code == 422, malformed.text
            wrong_type = await client.post(
                "/recall",
                content=b"plain text",
                headers={"Content-Type": "text/plain"},
            )
            assert wrong_type.status_code == 415, wrong_type.text

        # A full backend restart must reuse the same PowerContext scope.
        async with await _client() as client:
            restored = await client.post(
                "/recall",
                data={"player_id": "smoke-player", "query": "还记得我叫什么吗？"},
            )
            restored.raise_for_status()
            assert "阿岚" in restored.text, f"memory lost after restart:\n{restored.text}"

    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
