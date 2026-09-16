from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.providers.base import ChatMessage, ModelProvider
from app.providers.completion_text import EMPTY_GENERATION_ERROR


class _FakeMessage:
    def __init__(self, content=None, reasoning_content=None, tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls or []
        self.model_extra = {"reasoning_content": reasoning_content} if reasoning_content else {}

    def model_dump(self, exclude_none=True):
        payload = {"role": "assistant", "content": self.content}
        if self.reasoning_content:
            payload["reasoning_content"] = self.reasoning_content
        return payload


class _FakeChoice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason
        self.delta = None


class _FakeResponse:
    def __init__(self, message, finish_reason="stop"):
        self.choices = [_FakeChoice(message, finish_reason)]
        self.usage = None

    def model_dump(self, exclude_none=True):
        message = self.choices[0].message.model_dump()
        return {
            "choices": [
                {
                    "message": message,
                    "finish_reason": self.choices[0].finish_reason,
                }
            ]
        }


class _FakeDelta:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content
        extra = {}
        if reasoning_content:
            extra["reasoning_content"] = reasoning_content
        self.model_extra = extra

    def model_dump(self, exclude_none=True):
        payload = {}
        if self.content:
            payload["content"] = self.content
        if self.reasoning_content:
            payload["reasoning_content"] = self.reasoning_content
        return payload


class _FakeStreamChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason
        self.message = None


class _FakeChunk:
    def __init__(self, delta, finish_reason=None):
        self.choices = [_FakeStreamChoice(delta, finish_reason)]


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def _gen():
            for chunk in self._chunks:
                yield chunk

        return _gen()


class _FakeCompletions:
    def __init__(self, response=None, stream=None):
        self.response = response
        self.stream = stream
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if kwargs.get("stream"):
            return self.stream
        return self.response


def _provider_with(create_api: _FakeCompletions) -> ModelProvider:
    provider = ModelProvider("http://127.0.0.1:9/v1", model="qwen3.8-test")
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=create_api))
    return provider


@pytest.mark.asyncio
async def test_chat_uses_reasoning_content_when_message_content_is_empty():
    message = _FakeMessage(
        content="",
        reasoning_content="Latest markets were mixed, with energy shares lower.",
    )
    api = _FakeCompletions(_FakeResponse(message, finish_reason="length"))
    provider = _provider_with(api)

    result = await provider.chat(
        [ChatMessage(role="user", content="what latest news?")],
        max_tokens=256,
        thinking=False,
    )

    assert "markets were mixed" in result.content
    assert result.reasoning.startswith("Latest markets")
    assert api.kwargs["max_tokens"] == 256


@pytest.mark.asyncio
async def test_chat_stream_emits_reasoning_when_content_deltas_are_empty():
    stream = _FakeStream(
        [
            _FakeChunk(_FakeDelta(content="", reasoning_content="Headlines: ")),
            _FakeChunk(_FakeDelta(content="", reasoning_content="sterling firmed."), finish_reason="length"),
        ]
    )
    api = _FakeCompletions(stream=stream)
    provider = _provider_with(api)

    parts: list[str] = []
    async for delta in provider.chat_stream(
        [ChatMessage(role="user", content="what latest news?")],
        max_tokens=2048,
        thinking=None,
    ):
        parts.append(delta)

    assert "".join(parts) == "Headlines: sterling firmed."


@pytest.mark.asyncio
async def test_chat_stream_raises_real_error_when_both_channels_are_empty():
    stream = _FakeStream([_FakeChunk(_FakeDelta(content=""), finish_reason="length")])
    api = _FakeCompletions(stream=stream)
    provider = _provider_with(api)

    with pytest.raises(RuntimeError, match="finish_reason=length") as raised:
        async for _delta in provider.chat_stream([ChatMessage(role="user", content="hello")]):
            pass

    assert EMPTY_GENERATION_ERROR.split(".")[0] in str(raised.value)
    assert "couldn't form a reply" not in str(raised.value).lower()
