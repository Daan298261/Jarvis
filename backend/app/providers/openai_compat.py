import asyncio
import time

from .base import (
    ChatMessage,
    ChatResult,
    ModelProvider,
    StreamStallError,
    _STREAM_END,
    _anext_or_end,
    _timeout_s,
    close_chat_stream,
    parse_tool_arguments,
    to_openai_messages,
)

__all__ = [
    "ChatMessage",
    "ChatResult",
    "ModelProvider",
    "OpenAICompatProvider",
    "parse_tool_arguments",
    "to_openai_messages",
]


class OpenAICompatProvider(ModelProvider):
    """Named alias for the default OpenAI-compatible provider (local llama.cpp or remote LAN)."""

    name = "openai-compat"

    async def chat(self, messages, tools=None, temperature=None, top_p=None, top_k=None,
                   max_tokens=None, thinking=None, extra=None, call_deadline_ms=None,
                   stream_lane=None, prompt_token_estimate=None):
        from . import local_qwen_text as text
        if text.eligible(messages, tools, thinking, extra) and await text.admitted(self):
            result = await self._await_call_deadline(
                self.client.completions.create(**text.arguments(
                    self, messages, temperature, top_p, top_k, max_tokens, extra)),
                call_deadline_ms=call_deadline_ms,
                stream_lane=stream_lane,
                prompt_token_estimate=prompt_token_estimate,
            )
            from .completion_text import visible_completion_text
            content = visible_completion_text(result.choices[0].text)
            if not content:
                raise RuntimeError("Local Qwen text completion returned no visible answer")
            return ChatResult(content=content, usage=result.usage.model_dump() if result.usage else {})
        return await super().chat(messages, tools=tools, temperature=temperature, top_p=top_p,
                                  top_k=top_k, max_tokens=max_tokens, thinking=thinking, extra=extra,
                                  call_deadline_ms=call_deadline_ms, stream_lane=stream_lane,
                                  prompt_token_estimate=prompt_token_estimate)

    async def chat_stream(
        self,
        messages,
        *,
        temperature=None,
        top_p=None,
        top_k=None,
        max_tokens=None,
        thinking=None,
        extra=None,
        first_token_deadline_ms=None,
        idle_deadline_ms=None,
        stream_lane=None,
        prompt_token_estimate=None,
    ):
        """Accept the stall budgets ``InferenceManager`` always passes through.

        The local text-completion shortcut and the chat-completions path both
        honour the same first-token and idle deadlines. Dropping the kwargs
        raised ``TypeError`` on every owner chat turn.
        """
        from . import local_qwen_text as text
        if text.eligible(messages, None, thinking, extra) and await text.admitted(self):
            async for delta in self._local_text_chat_stream(
                messages,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                max_tokens=max_tokens,
                extra=extra,
                first_token_deadline_ms=first_token_deadline_ms,
                idle_deadline_ms=idle_deadline_ms,
                stream_lane=stream_lane,
                prompt_token_estimate=prompt_token_estimate,
            ):
                yield delta
            return
        async for delta in super().chat_stream(
            messages,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            max_tokens=max_tokens,
            thinking=thinking,
            extra=extra,
            first_token_deadline_ms=first_token_deadline_ms,
            idle_deadline_ms=idle_deadline_ms,
            stream_lane=stream_lane,
            prompt_token_estimate=prompt_token_estimate,
        ):
            yield delta

    async def _local_text_chat_stream(
        self,
        messages,
        *,
        temperature,
        top_p,
        top_k,
        max_tokens,
        extra,
        first_token_deadline_ms,
        idle_deadline_ms,
        stream_lane,
        prompt_token_estimate,
    ):
        from . import local_qwen_text as text

        first_timeout = _timeout_s(first_token_deadline_ms)
        idle_timeout = _timeout_s(idle_deadline_ms)
        started = time.perf_counter()
        last_chunk_at = started
        stream = None
        try:
            create = self.client.completions.create(
                stream=True,
                **text.arguments(self, messages, temperature, top_p, top_k, max_tokens, extra),
            )
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
                        budget_ms=float(first_token_deadline_ms or 0.0),
                        prompt_tokens=prompt_token_estimate,
                        lane=stream_lane,
                    )
                    await self._raise_stream_stall(
                        stall, stream, lane=stream_lane, prompt_tokens=prompt_token_estimate
                    )
                    return
            iterator = stream.__aiter__()
            yielded = False
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
                piece = getattr(choice, "text", None) or ""
                if piece:
                    yielded = True
                    yield piece
            if not yielded:
                raise RuntimeError("Local Qwen text stream returned no visible answer")
        except StreamStallError:
            raise
        finally:
            await close_chat_stream(stream)
