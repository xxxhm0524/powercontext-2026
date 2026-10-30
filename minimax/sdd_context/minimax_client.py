"""MiniMax API adapter used by the SDD development workflow.

MiniMax exposes several compatible surfaces.  This client supports the native
``/text/chatcompletion_v2`` API (default), the Anthropic-compatible endpoint
used by MiniMax coding plans, and plain OpenAI-compatible gateways.  Every call
can be written to a JSONL transcript so the submitted development record is
verifiable and directly tied to the generated patch.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .http_ssl import build_ssl_context


@dataclass
class MiniMaxConfig:
    api_key: str = ""
    base_url: str = "https://api.minimaxi.com/anthropic"
    model: str = "MiniMax-M2.5"
    api_style: str = "anthropic"  # anthropic | native | openai
    timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> "MiniMaxConfig":
        from .config import _load_dotenv

        _load_dotenv()
        return cls(
            api_key=os.environ.get("MINIMAX_API_KEY", "").strip(),
            base_url=os.environ.get("MINIMAX_BASE_URL", cls.base_url).rstrip("/"),
            model=os.environ.get("MINIMAX_MODEL", cls.model),
            api_style=os.environ.get("MINIMAX_API_STYLE", cls.api_style).lower(),
            timeout_seconds=float(os.environ.get("MINIMAX_TIMEOUT_SECONDS", "120")),
        )

    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class ChatResult:
    content: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    provider: str = "minimax"
    api_style: str = "native"


class MiniMaxError(RuntimeError):
    pass


class MiniMaxClient:
    def __init__(self, config: MiniMaxConfig | None = None, *, record_path: Path | None = None) -> None:
        self.config = config or MiniMaxConfig.from_env()
        self.record_path = record_path
        self._client = httpx.Client(timeout=self.config.timeout_seconds, verify=build_ssl_context())

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MiniMaxClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 8000,
        purpose: str = "sdd-context-demo",
    ) -> ChatResult:
        if not self.config.configured():
            raise MiniMaxError(
                "MINIMAX_API_KEY is not configured. Set it to a MiniMax platform key "
                "(see README section 'MiniMax 接入')."
            )
        started = time.perf_counter()
        if self.config.api_style == "anthropic":
            result = self._chat_anthropic(messages, system=system, temperature=temperature, max_tokens=max_tokens)
        elif self.config.api_style == "openai":
            result = self._chat_openai(messages, system=system, temperature=temperature, max_tokens=max_tokens)
        else:
            result = self._chat_native(messages, system=system, temperature=temperature, max_tokens=max_tokens)
        result.latency_ms = round((time.perf_counter() - started) * 1000, 2)
        self._record(messages, system, result, purpose=purpose)
        return result

    # ------------------------------------------------------------------ APIs
    def _chat_native(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> ChatResult:
        payload_messages = list(messages)
        if system:
            payload_messages = [{"role": "system", "content": system}, *payload_messages]
        response = self._client.post(
            f"{self.config.base_url}/text/chatcompletion_v2",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": payload_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
        )
        self._raise_for_status(response)
        data = response.json()
        base_resp = data.get("base_resp") if isinstance(data, dict) else None
        if isinstance(base_resp, dict) and int(base_resp.get("status_code", 0) or 0) != 0:
            raise MiniMaxError(
                f"MiniMax error {base_resp.get('status_code')}: {base_resp.get('status_msg')}"
            )
        content = _extract_native_content(data)
        usage = data.get("usage") if isinstance(data, dict) else None
        return ChatResult(
            content=content,
            model=self.config.model,
            usage=usage if isinstance(usage, dict) else {},
            raw=data,
            provider="minimax",
            api_style="native",
        )

    def _chat_anthropic(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        response = self._client.post(
            f"{self.config.base_url}/v1/messages",
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        self._raise_for_status(response)
        data = response.json()
        content = ""
        for block in data.get("content", []) if isinstance(data, dict) else []:
            if isinstance(block, dict) and block.get("type") == "text":
                content += str(block.get("text", ""))
        return ChatResult(
            content=content,
            model=self.config.model,
            usage=data.get("usage", {}) if isinstance(data, dict) else {},
            raw=data,
            provider="minimax",
            api_style="anthropic",
        )

    def _chat_openai(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> ChatResult:
        payload_messages = list(messages)
        if system:
            payload_messages = [{"role": "system", "content": system}, *payload_messages]
        response = self._client.post(
            f"{self.config.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": payload_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        self._raise_for_status(response)
        data = response.json()
        content = ""
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if choices:
            content = str(choices[0].get("message", {}).get("content", ""))
        return ChatResult(
            content=content,
            model=self.config.model,
            usage=data.get("usage", {}) if isinstance(data, dict) else {},
            raw=data,
            provider="minimax",
            api_style="openai",
        )

    # --------------------------------------------------------------- records
    def _record(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        result: ChatResult,
        *,
        purpose: str,
    ) -> None:
        if not self.record_path:
            return
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_text = (system or "") + "\n" + "\n".join(message.get("content", "") for message in messages)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "purpose": purpose,
            "provider": result.provider,
            "api_style": result.api_style,
            "base_url": self.config.base_url,
            "model": result.model,
            "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
            "request": {"system": system, "messages": messages},
            "response": {
                "content": result.content,
                "usage": result.usage,
            },
            "latency_ms": result.latency_ms,
        }
        with self.record_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            body = response.text[:1000]
            raise MiniMaxError(f"MiniMax HTTP {response.status_code}: {body}")


def _extract_native_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
            )
    # A few MiniMax endpoints return a direct reply field.
    for key in ("reply", "output_text", "text"):
        if isinstance(data.get(key), str):
            return str(data[key])
    return ""
