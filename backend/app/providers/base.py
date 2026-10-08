from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

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
    # ``internal`` marks agent instructions. Inference still sends ``role``,
    # but the owner transcript must not attribute that text to the user.
    audience: str = ""


@dataclass
class ChatResult:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def is_local_inference_url(base_url: str) -> bool:
    """True for loopback and private hosts. Cloud APIs keep SDK retries."""
    host = (urlparse(base_url or "").hostname or "").strip("[]").lower()
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


class StreamStallError(Exception):
    """Typed outcome when a caller-supplied first-token, idle, or call deadline is exceeded."""

    def __init__(
        self,
        *,
        deadline: Literal["first_token", "idle", "call"],
        elapsed_ms: float,
        budget_ms: float,
        provider: str,
        model: str,
        prompt_tokens: int | None = None,
        lane: str | None = None,
    ) -> None:
        self.deadline = deadline
        self.elapsed_ms = float(elapsed_ms)
        self.budget_ms = float(budget_ms)
        self.provider = str(provider or "")
        self.model = str(model or "")
        self.prompt_tokens = int(prompt_tokens) if prompt_tokens is not None else None
        self.lane = str(lane or "")
        kind = "call" if self.deadline == "call" else "stream"
        super().__init__(
            f"Model {kind} stalled ({self.deadline}): elapsed {self.elapsed_ms:.0f}ms "
            f"exceeded budget {self.budget_ms:.0f}ms for {self.provider}/{self.model}"
        )


def _timeout_s(deadline_ms: float | None) -> float | None:
    """``None`` means no guard. A supplied value is always treated as a deadline."""
    if deadline_ms is None:
        return None
    return max(0.0, float(deadline_ms) / 1000.0)


async def close_chat_stream(stream: Any) -> None:
    """Cancel/close the underlying streaming request. Safe to call more than once."""
    if stream is None:
        return
    for name in ("aclose", "close"):
        closer = getattr(stream, name, None)
        if not callable(closer):
            continue
        try:
            result = closer()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass
        break
    response = getattr(stream, "response", None)
    if response is None:
        return
    closer = getattr(response, "aclose", None) or getattr(response, "close", None)
    if not callable(closer):
        return
    try:
        result = closer()
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass


async def _anext_or_end(iterator: Any) -> Any:
    try:
        return await anext(iterator)
    except StopAsyncIteration:
        return _STREAM_END


_STREAM_END = object()


def to_openai_messages(
    messages: list[ChatMessage],
    *,
    for_inference: bool = True,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        content: str | list[dict[str, Any]] = message.content
        if content is None:
            content = ""
        item: dict[str, Any] = {"role": message.role, "content": content}
        if message.name:
            item["name"] = message.name
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            wired = normalize_tool_calls(message.tool_calls)
            if wired:
                item["tool_calls"] = wired
                if item["content"] is None:
                    item["content"] = ""
        if message.role == "tool" and not item.get("tool_call_id"):
            item["tool_call_id"] = "missing"
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
        self.local_inference = is_local_inference_url(self.base_url)
        # Local llama.cpp hangs are not transient. The SDK default of two retries
        # turns one 600s timeout into many minutes. Cloud hosts keep that default.
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=0 if self.local_inference else 2,
        )

    async def health(self) -> bool:
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        from ..policy.network_http import require_http_url_allowed

        try:
            require_http_url_allowed(root.rstrip("/") + "/health", tool="web_fetch")
        except PermissionError:
            return False
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
        call_deadline_ms: float | None = None,
        stream_lane: str | None = None,
        prompt_token_estimate: int | None = None,
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
            raw = await self._await_call_deadline(
                self.client.post("/chat/completions", cast_to=dict[str, Any], body=body),
                call_deadline_ms=call_deadline_ms,
                stream_lane=stream_lane,
                prompt_token_estimate=prompt_token_estimate,
            )
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
            response = await self._await_call_deadline(
                self.client.chat.completions.create(**kwargs),
                call_deadline_ms=call_deadline_ms,
                stream_lane=stream_lane,
                prompt_token_estimate=prompt_token_estimate,
            )
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

    async def _await_call_deadline(
        self,
        awaitable: Any,
        *,
        call_deadline_ms: float | None,
        stream_lane: str | None,
        prompt_token_estimate: int | None,
    ) -> Any:
        """Bound a non-streaming completion. ``None`` means no guard."""
        timeout = _timeout_s(call_deadline_ms)
        started = time.perf_counter()
        try:
            if timeout is None:
                return await awaitable
            return await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.TimeoutError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            stall = self._stream_stall(
                deadline="call",
                elapsed_ms=elapsed_ms,
                budget_ms=float(call_deadline_ms or 0.0),
                prompt_tokens=prompt_token_estimate,
                lane=stream_lane,
            )
            from ..inference.stream_deadlines import record_stream_stall

            record_stream_stall(
                stall,
                lane=stream_lane or stall.lane,
                prompt_token_estimate=prompt_token_estimate,
            )
            raise stall from exc

    def _stream_stall(
        self,
        *,
        deadline: Literal["first_token", "idle", "call"],
        elapsed_ms: float,
        budget_ms: float,
        prompt_tokens: int | None,
        lane: str | None,
    ) -> StreamStallError:
        return StreamStallError(
            deadline=deadline,
            elapsed_ms=elapsed_ms,
            budget_ms=budget_ms,
            provider=self.name,
            model=self.model,
            prompt_tokens=prompt_tokens,
            lane=lane,
        )

    async def _raise_stream_stall(
        self,
        stall: StreamStallError,
        stream: Any,
        *,
        lane: str | None,
        prompt_tokens: int | None,
    ) -> None:
        await close_chat_stream(stream)
        from ..inference.stream_deadlines import record_stream_stall

        record_stream_stall(stall, lane=lane or stall.lane, prompt_token_estimate=prompt_tokens)
        raise stall

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
        first_token_deadline_ms: float | None = None,
        idle_deadline_ms: float | None = None,
        stream_lane: str | None = None,
        prompt_token_estimate: int | None = None,
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
        first_timeout = _timeout_s(first_token_deadline_ms)
        idle_timeout = _timeout_s(idle_deadline_ms)
        started = time.perf_counter()
        last_chunk_at = started
        stream: Any = None
        try:
            create = self.client.chat.completions.create(**kwargs)
            if first_timeout is None:
                stream = await create
            else:
                try:
                    stream = await asyncio.wait_for(create, timeout=first_timeout)
                except asyncio.TimeoutError:
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    stall = self._stream_stall(
                        deadline="first_token",
                        elapsed_ms=elapsed_ms,
                        budget_ms=float(first_token_deadline_ms) if first_token_deadline_ms is not None else 0.0,
                        prompt_tokens=prompt_token_estimate,
                        lane=stream_lane,
                    )
                    await self._raise_stream_stall(
                        stall, stream, lane=stream_lane, prompt_tokens=prompt_token_estimate
                    )
                    return
            iterator = stream.__aiter__()
            yielded = False
            reasoning_parts: list[str] = []
            finish_reason: str | None = None
            got_chunk = False
            while True:
                if not got_chunk:
                    remaining = None if first_timeout is None else max(
                        0.0, first_timeout - (time.perf_counter() - started)
                    )
                else:
                    remaining = idle_timeout
                try:
                    if remaining is None:
                        chunk = await _anext_or_end(iterator)
                    else:
                        chunk = await asyncio.wait_for(_anext_or_end(iterator), timeout=remaining)
                except asyncio.TimeoutError:
                    elapsed_ms = (time.perf_counter() - (started if not got_chunk else last_chunk_at)) * 1000.0
                    budget = first_token_deadline_ms if not got_chunk else idle_deadline_ms
                    stall = self._stream_stall(
                        deadline="first_token" if not got_chunk else "idle",
                        elapsed_ms=elapsed_ms,
                        budget_ms=float(budget) if budget is not None else 0.0,
                        prompt_tokens=prompt_token_estimate,
                        lane=stream_lane,
                    )
                    await self._raise_stream_stall(
                        stall, stream, lane=stream_lane, prompt_tokens=prompt_token_estimate
                    )
                    return
                if chunk is _STREAM_END:
                    break
                got_chunk = True
                last_chunk_at = time.perf_counter()
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
        except StreamStallError:
            raise
        finally:
            await close_chat_stream(stream)


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
