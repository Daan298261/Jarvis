"""Resident front lane: CPU 2B default, GPU 4B fit, remote fallback, overlap."""

from __future__ import annotations

import asyncio

import pytest

from app.config import AppSettings, FrontResponderSettings
from app.inference.backends import LlamaCppBackend
from app.inference.front_runtime import FRONT_RUNTIME
from app.inference.manager import MANAGER
from app.inference.profiles import PROFILES
from app.persona.owner_chat import reset_owner_conversations, stream_owner_chat
from app.providers.base import ChatMessage


@pytest.fixture(autouse=True)
def _reset_front_runtime():
    FRONT_RUNTIME.reset_for_tests()
    yield
    FRONT_RUNTIME.reset_for_tests()


def _front_settings(**overrides) -> AppSettings:
    settings = AppSettings()
    for key, value in overrides.items():
        setattr(settings.front_responder, key, value)
    return settings


def test_default_front_choice_is_cpu_2b_and_timeout_stays_1500():
    fresh = FrontResponderSettings()
    assert fresh.model == ""
    assert fresh.profile == ""
    assert fresh.timeout_ms == 1500
    settings = _front_settings(profile="front_2b", device="auto", resident=True, enabled=True)
    decision = FRONT_RUNTIME.decide(
        settings,
        vram_total_mib=16384,
        vram_free_mib=200,
        ram_available_mib=48000,
        worker_loaded=True,
        gguf_present=True,
    )
    assert decision.mode == "resident"
    assert decision.device == "cpu"
    assert decision.n_gpu_layers == 0
    assert decision.reason.endswith("cpu_resident")
    assert decision.vram_required_mib == 0


def test_gpu_4b_vram_miss_records_numbers_and_does_not_claim_resident():
    settings = _front_settings(profile="front_4b", device="gpu", resident=True, enabled=True)
    decision = FRONT_RUNTIME.decide(
        settings,
        vram_total_mib=16384,
        vram_free_mib=900,
        ram_available_mib=48000,
        worker_loaded=False,
        gguf_present=True,
    )
    assert decision.mode == "fallback"
    assert decision.healthy is False
    assert "vram_insufficient" in decision.reason
    assert "free_mib=900" in decision.reason
    assert "total_mib=16384" in decision.reason
    assert "required_mib=" in decision.reason
    assert "voice_reserve_mib=" in decision.reason
    assert "worker_reserve_mib=" in decision.reason
    assert decision.vram_worker_reserve_mib > 0


def test_remote_unhealthy_falls_back_to_local_cpu_and_forced_is_visible():
    settings = _front_settings(
        profile="front_4b",
        device="gpu",
        placement="remote",
        placement_policy="FORCED",
        remote_base_url="http://10.1.2.3:8089/v1",
        remote_api_key="secret-front",
        resident=True,
        enabled=True,
    )
    missed = FRONT_RUNTIME.decide(
        settings,
        vram_total_mib=16384,
        vram_free_mib=12000,
        ram_available_mib=256,
        worker_loaded=True,
        remote_ok=False,
        remote_error="connection refused",
        gguf_present=True,
    )
    assert missed.fallback_from == "remote"
    assert missed.device == "cpu"
    assert missed.n_gpu_layers == 0
    assert "remote_unhealthy:connection refused" in missed.reason
    assert "force_not_honored" in missed.reason
    assert missed.mode == "fallback"
    assert "ram_insufficient" in missed.reason
    assert missed.ram_required_mib > 0
    assert "secret-front" not in missed.reason

    healthy = FRONT_RUNTIME.decide(
        settings,
        vram_total_mib=16384,
        vram_free_mib=12000,
        ram_available_mib=48000,
        worker_loaded=True,
        remote_ok=True,
        gguf_present=False,
    )
    assert healthy.mode == "remote"
    assert healthy.healthy is True
    assert healthy.device == "cpu"
    assert healthy.n_gpu_layers == 0
    assert healthy.endpoint == "http://10.1.2.3:8089/v1"
    assert healthy.reason == "remote_forced"


def test_missing_remote_endpoint_still_plans_local_cpu():
    settings = _front_settings(
        profile="front_2b",
        placement="remote",
        remote_base_url="",
        resident=True,
        enabled=True,
    )
    decision = FRONT_RUNTIME.decide(
        settings,
        vram_total_mib=None,
        vram_free_mib=None,
        ram_available_mib=48000,
        worker_loaded=True,
        gguf_present=True,
    )
    assert decision.fallback_from == "remote"
    assert "remote_endpoint_missing" in decision.reason
    assert decision.device == "cpu"
    assert decision.mode == "resident"


def test_front_server_args_are_cpu_cached_and_separate_from_worker():
    settings = AppSettings()
    backend = LlamaCppBackend(settings)
    profile = PROFILES["front_2b"]
    args = backend.build_args(
        profile,
        port=8089,
        reasoning=False,
        parallel=1,
        n_gpu_layers=0,
        keep=-1,
        prompt_cache=True,
    )
    assert "--n-gpu-layers" in args
    assert args[args.index("--n-gpu-layers") + 1] == "0"
    assert "--fit" not in args
    assert args[args.index("--keep") + 1] == "-1"
    assert "--parallel" in args
    assert "--no-cache-prompt" not in args
    assert args[args.index("--port") + 1] == "8089"
    worker = backend.build_args(PROFILES["fast"])
    assert worker[worker.index("--keep") + 1] == "0"
    assert "--parallel" not in worker


def test_front_provider_survives_worker_backend_stop():
    from app.agent.front_responder import front_provider

    sentinel = object()
    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=sentinel)

    class WorkerBackend:
        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    backend = WorkerBackend()
    MANAGER.backend = backend
    MANAGER.provider = None
    MANAGER.state.loaded = False

    async def _stop() -> None:
        await backend.stop()

    asyncio.run(_stop())
    assert backend.stopped is True
    assert FRONT_RUNTIME.provider() is sentinel
    assert front_provider(AppSettings()) is sentinel
    assert FRONT_RUNTIME.is_distinct() is True


def test_fixed_prompt_quality_matches_front_actions():
    from app.agent.front_benchmark import score_fixed_prompts

    report = score_fixed_prompts()
    assert report["prompts"] >= 8
    assert report["accuracy"] == 1.0
    assert report["spoken_usable"] == 1.0
    assert all(row["spoken_usable"] for row in report["rows"])


@pytest.mark.asyncio
async def test_terminal_turn_does_not_load_worker_even_when_front_is_distinct(jarvis_env, monkeypatch):
    del jarvis_env
    load_calls: list[str] = []

    class FrontProvider:
        model = "Qwen3.5-2B"

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Hello, sir."

    async def boom_load(*_args, **_kwargs):
        load_calls.append("load")
        raise AssertionError("terminal front must not load the worker")

    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=FrontProvider())
    MANAGER.provider = None
    MANAGER.state.loaded = False
    monkeypatch.setattr(MANAGER, "load", boom_load)
    reset_owner_conversations()

    events = []
    async for event in stream_owner_chat("Hello there"):
        events.append(event)

    assert load_calls == []
    assert events[-1]["type"] == "done"
    assert events[-1]["front_action"] == "final_basic"
    assert events[-1].get("front_terminal") is True


@pytest.mark.asyncio
async def test_worker_starts_during_front_reply_and_speaks_after_it(jarvis_env, monkeypatch):
    del jarvis_env
    worker_started = asyncio.Event()
    spoken: list[str] = []

    class FrontProvider:
        model = "Qwen3.5-2B"

        def __init__(self) -> None:
            self.saw_worker = False

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            try:
                await asyncio.wait_for(worker_started.wait(), timeout=2)
                self.saw_worker = True
            except TimeoutError:
                self.saw_worker = False
            yield "Checking the details."

    front = FrontProvider()

    async def worker_chat_stream(*_args, **_kwargs):
        worker_started.set()
        await asyncio.sleep(0.02)
        yield "It will be mild."

    async def no_messages(*_args, **_kwargs):
        return [ChatMessage(role="user", content="What's the weather tomorrow?")]

    async def no_context(*_args, **_kwargs):
        return {}

    async def no_weather(_text: str):
        return None

    async def no_hydrate(_conversation_id: str):
        return []

    def note_speech(text: str, **_kwargs):
        spoken.append(text)
        return f"tts-{len(spoken)}"

    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=front)
    MANAGER.state.loaded = True
    MANAGER.provider = front
    monkeypatch.setattr(MANAGER, "chat_stream", worker_chat_stream)
    monkeypatch.setattr("app.persona.owner_chat._owner_messages", no_messages)
    monkeypatch.setattr("app.persona.owner_chat.ensure_context_for_messages", no_context)
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", no_weather)
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", no_hydrate)
    monkeypatch.setattr("app.persona.owner_chat.maybe_enqueue_streaming_social_tts", note_speech)
    reset_owner_conversations()

    events = []
    async for event in stream_owner_chat("What's the weather tomorrow?"):
        events.append(event)

    assert front.saw_worker is True
    assert spoken
    assert spoken[0].startswith("Checking the details")
    assert any("mild" in line.lower() for line in spoken[1:])
    assert events[-1]["type"] == "done"
