from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import AsyncOpenAI


@dataclass
class ChatMessage:
    role: str
    content: str | list[dict[str, Any]]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    reasoning_content: str | None = None


@dataclass
class ChatResult:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def to_openai_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.name:
            item["name"] = message.name
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            item["tool_calls"] = message.tool_calls
        if message.reasoning_content:
            item["reasoning_content"] = message.reasoning_content
        out.append(item)
    return out


class ModelProvider:
    """OpenAI-compatible chat provider.

    Talks to local llama.cpp, another machine on the LAN, or a dedicated
    multi-GPU server through the same /v1/chat/completions contract.
    Subclass and override health/chat only when a backend is not OpenAI-compatible.
    """

    name: str = "openai-compat"

    def __init__(
        self,
        base_url: str,
        api_key: str = "local",
        model: str = "Qwen3.5-27B",
        timeout: float = 600,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.client = AsyncOpenAI(base_url=self.base_url, api_key=api_key, timeout=timeout)

    async def health(self) -> bool:
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                for path in ("/health", "/v1/models", "/models"):
                    try:
                        response = await client.get(root + path)
                        if response.status_code < 500:
                            return True
                    except Exception:
                        continue
                response = await client.get(self.base_url + "/models")
                return response.status_code < 500
        except Exception:
            return False

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ChatResult:
        extra_body: dict[str, Any] = dict(extra or {})
        extra_body.setdefault("chat_template_kwargs", {})
        if thinking is not None:
            extra_body["chat_template_kwargs"]["enable_thinking"] = bool(thinking)
            if not thinking:
                extra_body["reasoning_budget"] = 0
        if top_k is not None:
            extra_body["top_k"] = top_k
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if extra_body:
            kwargs["extra_body"] = extra_body
        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        tool_calls: list[dict[str, Any]] = []
        for call in message.tool_calls or []:
            tool_calls.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments or "{}",
                    },
                }
            )
        usage = {}
        if response.usage:
            usage = response.usage.model_dump()
        raw = response.model_dump()
        timings = raw.get("timings") if isinstance(raw.get("timings"), dict) else {}
        reasoning = getattr(message, "reasoning_content", None) or ""
        return ChatResult(
            content=message.content or "",
            reasoning=reasoning or "",
            tool_calls=tool_calls,
            usage=usage,
            timings=timings,
            raw=raw,
        )


def parse_tool_arguments(payload: str) -> dict[str, Any]:
    try:
        data = json.loads(payload or "{}")
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        return {"_raw": payload}


def tool_arguments_valid(payload: str | None) -> bool:
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict)
