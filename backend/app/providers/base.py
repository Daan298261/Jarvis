from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import AsyncOpenAI

from .tool_call_compat import normalize_tool_calls
from .completion_text import (
    content_text_from_payload,
    delta_text_channels,
    empty_generation_error,
    message_payload_from_openai,
    reasoning_text_from_payload,
    visible_completion_text,
)


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


def to_openai_messages(
    messages: list[ChatMessage],
    *,
    for_inference: bool = True,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.name:
            item["name"] = message.name
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            item["tool_calls"] = message.tool_calls
        if not for_inference and message.reasoning_content:
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
        if tools:
            # The SDK's typed ChatCompletion rejects llama.cpp builds that return
            # function.arguments as a JSON object. Keep OpenAI transport/error handling,
            # but parse this response as a plain dictionary before normalizing calls.
            body = {key: value for key, value in kwargs.items() if key != "extra_body"}
            body.update(extra_body)
            body["parallel_tool_calls"] = False
            raw = await self.client.post("/chat/completions", cast_to=dict[str, Any], body=body)
            choices = raw.get("choices") if isinstance(raw, dict) else None
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise RuntimeError("Inference server returned no chat completion choice")
            payload = choices[0].get("message") or {}
            if not isinstance(payload, dict):
                raise RuntimeError("Inference server returned an invalid chat message")
            raw_content = content_text_from_payload(payload)
            tool_calls = normalize_tool_calls(payload.get("tool_calls"), content=raw_content)
            usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
            reasoning = reasoning_text_from_payload(payload)
            content = visible_completion_text(raw_content, reasoning)
            if tool_calls and "<tool_call>" in raw_content:
                content = ""
        else:
            response = await self.client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            usage = response.usage.model_dump() if response.usage else {}
            raw = response.model_dump() if hasattr(response, "model_dump") else {}
            if not isinstance(raw, dict):
                raw = {}
            payload = message_payload_from_openai(message, raw)
            reasoning = reasoning_text_from_payload(payload) or getattr(message, "reasoning_content", None) or ""
            content = visible_completion_text(
                content_text_from_payload(payload) or getattr(message, "content", None) or "",
                reasoning,
            )
            tool_calls = []
        timings = raw.get("timings") if isinstance(raw.get("timings"), dict) else {}
        return ChatResult(
            content=content,
            reasoning=reasoning or "",
            tool_calls=tool_calls,
            usage=usage,
            timings=timings,
            raw=raw,
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
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
            "stream": True,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if extra_body:
            kwargs["extra_body"] = extra_body
        stream = await self.client.chat.completions.create(**kwargs)
        yielded = False
        reasoning_parts: list[str] = []
        finish_reason: str | None = None
        async for chunk in stream:
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            if not choice:
                continue
            reason = getattr(choice, "finish_reason", None)
            if reason:
                finish_reason = str(reason)
            delta = getattr(choice, "delta", None)
            content_delta, reasoning_delta = delta_text_channels(delta)
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
            if content_delta:
                yielded = True
                yield content_delta
        if not yielded:
            fallback = visible_completion_text("", "".join(reasoning_parts))
            if fallback:
                yield fallback
                return
            raise RuntimeError(empty_generation_error(finish_reason))


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
