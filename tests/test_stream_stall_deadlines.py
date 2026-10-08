"""Wave 1 T2: provider stream first-token / idle stall deadlines."""

from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

from app.config import AppSettings, FrontResponderSettings, InferenceSettings, SocialCommentarySettings
from app.inference.manager import InferenceManager
from app.inference.stream_deadlines import (
    compute_chat_stream_deadlines,
    compute_first_token_deadline_ms,
    record_stream_stall,
)
from app.tts.persona_speech import announce_stream_stall, stall_spoken_line, with_address
from app.providers.base import ChatMessage, ModelProvider, StreamStallError


class _FakeDelta:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content
        extra = {}
        if reasoning_content:
            extra["reasoning_content"] = reasoning_content
        self.model_extra = extra


class _FakeStreamChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason
        self.message = None


class _FakeChunk:
    def __init__(self, delta, finish_reason=None):
        self.choices = [_FakeStreamChoice(delta, finish_reason)]


class _DelayedStream:
    def __init__(self, chunks, *, delay_before=0.0, delay_between=0.0):
        self._chunks = list(chunks)
        self._delay_before = delay_before
        self._delay_between = delay_between
        self._index = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index == 0 and self._delay_before:
            await asyncio.sleep(self._delay_before)
        elif self._index > 0 and self._delay_between:
            await asyncio.sleep(self._delay_between)
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk

    async def aclose(self):
        self.closed = True


class _FakeCompletions:
    def __init__(self, stream=None, *, create_delay=0.0):
        self.stream = stream
        self.create_delay = create_delay
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.create_delay:
            await asyncio.sleep(self.create_delay)
        return self.stream


def _provider_with(create_api: _FakeCompletions) -> ModelProvider:
    provider = ModelProvider("http://127.0.0.1:9/v1", model="qwen3.8-test")
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=create_api))
    return provider


def _hello_chunk(text: str = "Hello", finish_reason=None) -> _FakeChunk:
    return _FakeChunk(_FakeDelta(content=text), finish_reason=finish_reason)


@pytest.fixture
def rolling_log_file(tmp_path, monkeypatch):
    from app.observability import rolling_log as rl

    path = tmp_path / "rolling-log.jsonl"
    monkeypatch.setattr(rl, "log_path", lambda: path)
    monkeypatch.setattr(rl, "_PRUNE_EVERY_WRITES", 100)
    return path


def _stall_events(path):
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("kind") == "inference_stream_stall"]


def test_chat_stream_has_no_hidden_budget_defaults():
    source = inspect.getsource(ModelProvider.chat_stream)
    params = inspect.signature(ModelProvider.chat_stream).parameters
    assert params["first_token_deadline_ms"].default is None
    assert params["idle_deadline_ms"].default is None
    assert "first_token_deadline_ms: float | None = None" in source
    assert "idle_deadline_ms: float | None = None" in source
    assert "1500" not in source
    assert "stream_first_token" not in source


def test_inference_settings_hold_stream_budget_defaults():
    settings = InferenceSettings()
    assert settings.stream_first_token_base_ms == 2500
    assert settings.stream_idle_ms == 12000
    assert settings.prompt_tps_fallback == 80.0
    assert settings.stream_first_token_min_ms == 3000
    assert settings.stream_first_token_max_ms == 180000


def test_first_token_deadline_scales_with_prompt_size():
    settings = InferenceSettings(
        stream_first_token_base_ms=2500,
        prompt_tps_fallback=50.0,
        stream_first_token_min_ms=0,
        stream_first_token_max_ms=180000,
    )
    small = compute_first_token_deadline_ms(settings, prompt_tokens=100, prompt_tps=None)
    large = compute_first_token_deadline_ms(settings, prompt_tokens=4000, prompt_tps=None)
    assert small == pytest.approx(2500 + (100 / 50.0) * 1000.0)
    assert large == pytest.approx(2500 + (4000 / 50.0) * 1000.0)
    assert large > small

    measured = compute_first_token_deadline_ms(settings, prompt_tokens=4000, prompt_tps=200.0)
    assert measured == pytest.approx(2500 + (4000 / 200.0) * 1000.0)

    capped = compute_first_token_deadline_ms(
        InferenceSettings(stream_first_token_base_ms=2500, prompt_tps_fallback=1.0, stream_first_token_min_ms=0, stream_first_token_max_ms=8000),
        prompt_tokens=50_000,
        prompt_tps=None,
    )
    assert capped == 8000

    floored = compute_first_token_deadline_ms(
        InferenceSettings(stream_first_token_base_ms=100, prompt_tps_fallback=80.0, stream_first_token_min_ms=4000, stream_first_token_max_ms=180000),
        prompt_tokens=1,
        prompt_tps=None,
    )
    assert floored == 4000

    first, idle = compute_chat_stream_deadlines(
        InferenceSettings(),
        prompt_tokens=800,
        prompt_tps=80.0,
    )
    assert idle == 12000
    assert first == pytest.approx(max(3000, 2500 + (800 / 80.0) * 1000.0))


@pytest.mark.asyncio
async def test_chat_stream_first_token_deadline(rolling_log_file):
    stream = _DelayedStream([_hello_chunk("too late", "stop")], delay_before=0.25)
    provider = _provider_with(_FakeCompletions(stream))

    with pytest.raises(StreamStallError) as raised:
        async for _delta in provider.chat_stream(
            [ChatMessage(role="user", content="hello")],
            first_token_deadline_ms=40,
            stream_lane="worker",
            prompt_token_estimate=12,
        ):
            pass

    stall = raised.value
    assert stall.deadline == "first_token"
    assert stall.budget_ms == 40
    assert stall.elapsed_ms >= 40
    assert stall.provider == "openai-compat"
    assert stall.model == "qwen3.8-test"
    assert stream.closed is True
    events = _stall_events(rolling_log_file)
    assert len(events) == 1
    event = events[0]
    assert event["lane"] == "worker"
    assert event["deadline"] == "first_token"
    assert event["budget_ms"] == 40
    assert event["elapsed_ms"] >= 40
    assert event["provider"] == "openai-compat"
    assert event["model"] == "qwen3.8-test"
    assert event["prompt_token_estimate"] == 12


@pytest.mark.asyncio
async def test_chat_stream_idle_deadline(rolling_log_file):
    stream = _DelayedStream(
        [_hello_chunk("Hello "), _hello_chunk("there.", "stop")],
        delay_between=0.25,
    )
    provider = _provider_with(_FakeCompletions(stream))
    parts: list[str] = []

    with pytest.raises(StreamStallError) as raised:
        async for delta in provider.chat_stream(
            [ChatMessage(role="user", content="hello")],
            idle_deadline_ms=40,
            stream_lane="worker",
            prompt_token_estimate=8,
        ):
            parts.append(delta)

    stall = raised.value
    assert stall.deadline == "idle"
    assert stall.budget_ms == 40
    assert stall.elapsed_ms >= 40
    assert parts == ["Hello "]
    assert stream.closed is True
    events = _stall_events(rolling_log_file)
    assert len(events) == 1
    assert events[0]["deadline"] == "idle"
    assert events[0]["lane"] == "worker"
    assert events[0]["prompt_token_estimate"] == 8


@pytest.mark.asyncio
async def test_chat_stream_no_guard_when_deadlines_not_supplied():
    stream = _DelayedStream([_hello_chunk("ok", "stop")], delay_before=0.12)
    provider = _provider_with(_FakeCompletions(stream))
    parts: list[str] = []
    async for delta in provider.chat_stream([ChatMessage(role="user", content="hello")]):
        parts.append(delta)
    assert parts == ["ok"]
    assert stream.closed is True


@pytest.mark.asyncio
async def test_front_lane_keeps_1500_ms_budget():
    from app.agent.front_responder import generate_front_reply

    captured: dict[str, object] = {}

    class CaptureProvider:
        async def chat_stream(self, messages, **kwargs):
            captured.update(kwargs)
            yield "Hello there."

    settings = AppSettings(front_responder=FrontResponderSettings())
    assert settings.front_responder.timeout_ms == 1500
    reply = await generate_front_reply("hello", provider=CaptureProvider(), settings=settings)
    assert captured["first_token_deadline_ms"] == 1500
    assert captured["idle_deadline_ms"] == 1500
    assert captured["stream_lane"] == "front"
    assert "Hello" in reply.text


@pytest.mark.asyncio
async def test_manager_chat_stream_passes_scaled_budgets():
    mgr = InferenceManager()
    mgr.state.context_size = 16384
    mgr.state.prompt_tps = 50.0
    captured: dict[str, object] = {}

    class Capture:
        async def chat_stream(self, messages, **kwargs):
            captured.update(kwargs)
            yield "Voice ok."

    mgr.provider = Capture()
    prompt = "x" * 400
    parts: list[str] = []
    async for delta in mgr.chat_stream(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=64,
        settings=AppSettings(),
    ):
        parts.append(delta)
    assert "".join(parts) == "Voice ok."
    assert captured["stream_lane"] == "worker"
    assert captured["idle_deadline_ms"] == 12000
    expected_first, expected_idle = compute_chat_stream_deadlines(
        AppSettings().inference,
        prompt_tokens=int(captured["prompt_token_estimate"]),
        prompt_tps=50.0,
    )
    assert captured["first_token_deadline_ms"] == expected_first
    assert captured["idle_deadline_ms"] == expected_idle
    assert int(captured["prompt_token_estimate"]) >= 1


def test_record_stream_stall_event_shape(rolling_log_file):
    stall = StreamStallError(
        deadline="idle",
        elapsed_ms=8123.4,
        budget_ms=12000,
        provider="openai-compat",
        model="Qwen3.5-27B",
        prompt_tokens=640,
        lane="worker",
    )
    event = record_stream_stall(stall, lane="worker", prompt_token_estimate=640)
    assert event["kind"] == "inference_stream_stall"
    rows = _stall_events(rolling_log_file)
    assert len(rows) == 1
    row = rows[0]
    assert row["lane"] == "worker"
    assert row["provider"] == "openai-compat"
    assert row["model"] == "Qwen3.5-27B"
    assert row["deadline"] == "idle"
    assert row["budget_ms"] == 12000
    assert row["elapsed_ms"] == 8123.4
    assert row["prompt_token_estimate"] == 640
    assert "stalled" in row["message"].lower()


def test_stall_speech_uses_address_resolver_not_hardcoded_sir():
    stall = StreamStallError(
        deadline="first_token",
        elapsed_ms=4000,
        budget_ms=3000,
        provider="openai-compat",
        model="qwen",
    )
    neutral = AppSettings(social_commentary=SocialCommentarySettings(address_style="neutral"))
    named = AppSettings(
        social_commentary=SocialCommentarySettings(
            address_style="configured",
            configured_address_name="Daan",
        )
    )
    sir = AppSettings(social_commentary=SocialCommentarySettings(address_style="sir_maam"))
    idle = StreamStallError(
        deadline="idle",
        elapsed_ms=9000,
        budget_ms=8000,
        provider="openai-compat",
        model="qwen",
    )

    neutral_line = stall_spoken_line(stall, neutral)
    named_line = stall_spoken_line(stall, named)
    sir_line = stall_spoken_line(stall, sir)
    idle_line = stall_spoken_line(idle, neutral)

    assert "stalled" in neutral_line.lower()
    assert "sir" not in neutral_line.lower()
    assert "Daan" in named_line
    assert "sir" not in named_line.lower()
    assert sir_line.lower().endswith("sir.")
    assert "stalled" in idle_line.lower()
    assert "middle" in idle_line.lower()
    assert "sir" not in with_address("The model stalled.", neutral).lower()


@pytest.mark.asyncio
async def test_spoken_failure_path_goes_through_speak_text(monkeypatch):
    spoken: list[str] = []

    async def fake_publish(text, **kwargs):
        spoken.append(text)
        return {"text": text, "spoken": True, "tts_id": "tts-1"}

    monkeypatch.setattr("app.persona.chat_delivery.publish_owner_text", fake_publish)
    stall = StreamStallError(
        deadline="first_token",
        elapsed_ms=5000,
        budget_ms=4000,
        provider="openai-compat",
        model="qwen",
    )
    settings = AppSettings(social_commentary=SocialCommentarySettings(address_style="neutral"))
    announced = await announce_stream_stall(stall, settings=settings, source="owner_chat")
    assert announced is True
    assert spoken
    assert "stalled" in spoken[0].lower()
    assert "sir" not in spoken[0].lower()

    skipped = await announce_stream_stall(RuntimeError("other"), settings=settings)
    assert skipped is False
    assert len(spoken) == 1
