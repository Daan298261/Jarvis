from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError

from app.config import AppSettings
from app.inference.backends import LlamaCppBackend
from app.inference.context_window import (
    clamp_n_keep,
    extract_loaded_n_ctx,
    n_keep_for_messages,
    n_keep_overflow_message,
    parse_n_keep_overflow,
)
from app.inference.manager import InferenceManager, fit_messages_to_context
from app.inference.profiles import resolve_profile
from app.providers.base import ChatMessage, ChatResult


N_KEEP_ERROR = (
    "Error code: 400 - {'error': 'The number of tokens to keep from the initial prompt is "
    "greater than the context length (n_keep: 6772 >= n_ctx: 4096). Try to load the model "
    "with a larger context length, or provide a shorter input.'}"
)


def _settings(**inference) -> AppSettings:
    base = {"backend": "llama.cpp", "host": "127.0.0.1", "port": 8088}
    base.update(inference)
    return AppSettings(inference=base)


def _status_error(message: str = N_KEEP_ERROR) -> APIStatusError:
    request = httpx.Request("POST", "http://127.0.0.1:8088/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return APIStatusError(message, response=response, body={"error": message})


def test_clamp_n_keep_rejects_prompt_sized_keep_on_4k_slot():
    kept = clamp_n_keep(6772, 4096, max_tokens=256)
    assert kept < 4096
    assert kept == clamp_n_keep(kept, 4096, max_tokens=256)


def test_n_keep_for_huge_system_prompt_fits_4k_with_generation_headroom():
    messages = [
        ChatMessage(role="system", content="persona and recovered context " * 800),
        ChatMessage(role="user", content="do a voice check"),
    ]
    keep = n_keep_for_messages(messages, 4096, max_tokens=1024)
    assert keep < 4096
    # Leave room for the completion: keep + generation must stay inside n_ctx.
    assert keep + 1024 <= 4096


def test_parse_n_keep_overflow_reads_llama_cpp_400():
    assert parse_n_keep_overflow(N_KEEP_ERROR) == (6772, 4096)
    assert parse_n_keep_overflow({"error": N_KEEP_ERROR}) == (6772, 4096)
    assert "n_keep: 6772" in n_keep_overflow_message(6772, 4096)
    assert "n_ctx: 4096" in n_keep_overflow_message(6772, 4096)


def test_extract_n_ctx_from_llama_cpp_props():
    payload = {
        "default_generation_settings": {
            "n_ctx": 4096,
            "params": {"n_keep": 0, "n_predict": -1},
        },
        "total_slots": 1,
    }
    assert extract_loaded_n_ctx(payload) == 4096


def test_extract_n_ctx_prefers_lmstudio_loaded_instance_over_model_max():
    payload = {
        "data": [
            {
                "id": "qwen-local",
                "max_context_length": 32768,
                "loaded_instances": [{"context_length": 4096, "n_gpu_layers": 16}],
            }
        ]
    }
    assert extract_loaded_n_ctx(payload) == 4096


def test_fit_messages_trims_recovered_context_for_4k_server():
    messages = [
        ChatMessage(role="system", content="system rules and recovered memory " * 2000),
        ChatMessage(role="user", content="old request " * 400),
        ChatMessage(role="assistant", content="old reply " * 400),
        ChatMessage(role="user", content="do a voice check"),
    ]
    fitted = fit_messages_to_context(messages, context_size=4096, max_tokens=256)
    chars = sum(len(str(message.content)) for message in fitted)
    # 2 chars/token estimate with 256 completion + 256 template reserve → 7168 chars.
    assert chars <= 7168
    assert fitted[-1].content == "do a voice check"
    keep = n_keep_for_messages(fitted, 4096, max_tokens=256)
    assert keep < 4096


def test_llama_cpp_args_default_keep_to_zero():
    args = LlamaCppBackend(_settings()).build_args(resolve_profile("balanced"))
    assert args[args.index("--keep") + 1] == "0"


@pytest.mark.asyncio
async def test_remote_load_adopts_live_n_ctx_instead_of_profile_cap(monkeypatch):
    settings = _settings(backend="lmstudio", host="127.0.0.1", port=1234, remote_model="qwen")
    mgr = InferenceManager()

    async def fake_probe(host, port, api_key="", timeout=8, retry=False):
        del host, port, api_key, timeout, retry
        return {"ok": True, "health_path": "/v1/models", "models": ["qwen"], "n_ctx": 4096}

    async def fake_health(self):
        return True

    monkeypatch.setattr("app.inference.manager.probe_remote_server", fake_probe)
    monkeypatch.setattr("app.providers.base.ModelProvider.health", fake_health)
    state = await mgr.load(settings, "balanced")
    assert state.loaded is True
    assert state.server_n_ctx == 4096
    assert state.context_size == 4096
    assert mgr.live_context_size() == 4096


@pytest.mark.asyncio
async def test_apply_context_cannot_inflate_past_loaded_slot():
    mgr = InferenceManager()
    mgr.backend = None
    mgr.state.context_size = 4096
    mgr.state.server_n_ctx = 4096
    grown = await mgr.apply_context(AppSettings(), 16384, allow_shrink=False)
    assert grown == 4096
    assert mgr.state.context_size == 4096


@pytest.mark.asyncio
async def test_chat_retries_after_n_keep_overflow_and_refits_to_live_n_ctx():
    mgr = InferenceManager()
    mgr.state.context_size = 16384
    mgr.state.server_n_ctx = 0
    mgr.state.backend = "lmstudio"
    mgr.state.health_path = "/v1/models"
    captured: dict[str, list] = {"extras": [], "sizes": []}

    class OverflowThenOk:
        calls = 0

        async def chat(self, messages, **kwargs):
            captured["extras"].append(dict(kwargs.get("extra") or {}))
            captured["sizes"].append(sum(len(str(getattr(item, "content", "") or "")) for item in messages))
            OverflowThenOk.calls += 1
            if OverflowThenOk.calls == 1:
                raise _status_error()
            return ChatResult(content="Voice check complete.")

    mgr.provider = OverflowThenOk()
    messages = [
        ChatMessage(role="system", content="recovered conversation and persona " * 2500),
        ChatMessage(role="user", content="do a voice check"),
    ]
    result = await mgr.chat(messages, max_tokens=256)
    assert result.content == "Voice check complete."
    assert OverflowThenOk.calls == 2
    assert mgr.state.server_n_ctx == 4096
    assert mgr.state.context_size == 4096
    assert captured["extras"][1]["n_keep"] < 4096
    assert captured["sizes"][1] < captured["sizes"][0]


@pytest.mark.asyncio
async def test_chat_stream_retries_after_n_keep_overflow():
    mgr = InferenceManager()
    mgr.state.context_size = 16384
    mgr.state.backend = "llama.cpp"
    mgr.state.health_path = "/health"

    class OverflowThenStream:
        calls = 0

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            OverflowThenStream.calls += 1
            if OverflowThenStream.calls == 1:
                raise _status_error()
            yield "Voice "
            yield "ok."

    mgr.provider = OverflowThenStream()
    parts: list[str] = []
    async for delta in mgr.chat_stream(
        [ChatMessage(role="user", content="do a voice check")],
        max_tokens=256,
    ):
        parts.append(delta)
    assert "".join(parts) == "Voice ok."
    assert OverflowThenStream.calls == 2
    assert mgr.live_context_size() == 4096


@pytest.mark.asyncio
async def test_explicit_n_keep_minus_one_is_clamped_below_n_ctx():
    mgr = InferenceManager()
    mgr.state.context_size = 4096
    mgr.state.server_n_ctx = 4096
    mgr.state.backend = "llama.cpp"
    captured: dict[str, dict] = {}

    class Capture:
        async def chat(self, messages, **kwargs):
            del messages
            captured["extra"] = dict(kwargs.get("extra") or {})
            return ChatResult(content="ok")

    mgr.provider = Capture()
    await mgr.chat(
        [ChatMessage(role="system", content="x" * 20000), ChatMessage(role="user", content="hi")],
        extra={"n_keep": -1},
        max_tokens=256,
    )
    assert captured["extra"]["n_keep"] < 4096
    assert captured["extra"]["n_keep"] >= 0
