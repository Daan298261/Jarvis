"""RFC-0206 slices 4–5: literal ready fixture and self-knowledge snapshot."""

from __future__ import annotations

import json

import pytest

from app.agent.front_responder import (
    SAFE_ACK,
    classify_front_action,
    enforce_front_safety,
    fallback_text_for_action,
    generate_front_reply,
    run_two_lane_chat,
    small_context_envelope,
    worker_required,
)
from app.agent.self_knowledge import (
    PRODUCT_NAME,
    SNAPSHOT_INCLUDE_KEYS,
    build_self_knowledge_snapshot,
    snapshot_covers_question,
    snapshot_prompt_addendum,
)

_FORBIDDEN_PROMPT_FRAGMENTS = (
    "auth_token",
    "api_key",
    "remote_api_key",
    "voicestudio_api_key",
    "model_path",
    "gguf_path",
    "mmproj_path",
    "vault_path",
    "remote_base_url",
    "mcp_servers",
    "tool catalog",
    "tool_catalog",
)


def _forbidden_snapshot_leak(rendered: str) -> list[str]:
    hay = (rendered or "").lower()
    return [item for item in _FORBIDDEN_PROMPT_FRAGMENTS if item in hay]
from app.config import AppSettings, FrontResponderSettings, InferenceSettings, KnowledgeVaultSettings, VoiceSettings
from app.decision.owner_turn import decide_owner_turn
from app.agent.planning import route_request
from app.providers.base import ChatMessage


@pytest.mark.asyncio
async def test_say_only_the_word_ready_is_literal_final_basic():
    turn = await decide_owner_turn(
        "Say only the word ready",
        baseline=route_request("Say only the word ready"),
        decision_tier="local",
    )
    assert turn.literal_text == "ready"
    assert turn.reply_shape == "literal"
    assert turn.front_action == "final_basic"
    assert worker_required(turn.front_action) is False
    assert classify_front_action("Say only the word ready", decision=turn) == "final_basic"


@pytest.mark.asyncio
async def test_ready_fixture_short_circuits_provider_to_literal():
    class AckProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield SAFE_ACK

    reply = await generate_front_reply(
        "Say only the word ready",
        settings=AppSettings(),
        provider=AckProvider(),
    )
    assert reply.action == "final_basic"
    assert reply.text == "ready"
    assert SAFE_ACK not in reply.text
    assert worker_required(reply.action) is False


@pytest.mark.asyncio
async def test_ready_fixture_when_front_provider_missing():
    reply = await generate_front_reply(
        "Say only the word ready",
        settings=AppSettings(),
        provider=object(),
    )
    assert reply.action == "final_basic"
    assert reply.text == "ready"


@pytest.mark.asyncio
async def test_two_lane_ready_does_not_start_worker():
    started = []

    async def worker():
        started.append(True)
        yield "should not run"

    events = []
    async for event in run_two_lane_chat(
        "Say only the word ready",
        settings=AppSettings(),
        worker_stream=worker,
    ):
        events.append(event)
    done = events[-1]
    assert done["type"] == "done"
    assert done["text"] == "ready"
    assert done["front_action"] == "final_basic"
    assert started == []
    assert "worker_response_started" not in [event.get("type") for event in events]


@pytest.mark.asyncio
async def test_empty_ack_still_uses_safe_ack():
    class Empty:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            if False:
                yield ""

    reply = await generate_front_reply(
        "what is the weather in dinteloord, tomorrow",
        settings=AppSettings(),
        provider=Empty(),
    )
    assert reply.action == "ack_continue"
    assert reply.text == SAFE_ACK


def test_fallback_does_not_use_safe_ack_for_literal_social_or_clarify():
    assert fallback_text_for_action("final_basic", reply_shape="literal", literal_text="ready") == "ready"
    assert SAFE_ACK not in fallback_text_for_action("final_basic", reply_shape="social")
    assert fallback_text_for_action("ask_clarification", reply_shape="clarify") != SAFE_ACK
    assert fallback_text_for_action("ack_continue", reply_shape="ack") == SAFE_ACK
    assert fallback_text_for_action("final_basic", reply_shape="self_status") == ""
    assert "live self snapshot" not in fallback_text_for_action("final_basic", reply_shape="self_status")


def test_enforce_replaces_holding_phrase_on_literal():
    action, text, rejected = enforce_front_safety(
        "ack_continue",
        SAFE_ACK,
        user_text="Say only the word ready",
        heuristic="final_basic",
        reply_shape="literal",
        literal_text="ready",
    )
    assert action == "final_basic"
    assert text == "ready"
    assert rejected is True


def test_snapshot_include_and_exclude(jarvis_env):
    settings = jarvis_env["settings"]
    settings.auth_token = "super-secret-token"
    settings.inference.api_key = "inference-secret"
    settings.front_responder.remote_api_key = "front-secret"
    settings.front_responder.remote_base_url = "http://127.0.0.1:9999/v1"
    settings.voice.voicestudio_api_key = "voice-secret"
    settings.knowledge_vault.vault_path = "/home/owner/vault"
    settings.named_personas.active_id = "anzu"
    settings.inference.profile = "fast"
    settings.inference.context_size = 16384
    state = jarvis_env["manager"].state
    state.loaded = True
    state.profile = "fast"
    state.alias = "qwen-fast"
    state.backend = "llama.cpp"
    state.context_size = 16384
    state.server_n_ctx = 8192
    state.family = "9b"
    state.pid = 4321
    state.model_path = "/opt/models/secret.gguf"
    state.gguf_path = "/opt/models/secret.gguf"
    state.mmproj_path = "/opt/models/mmproj.gguf"

    snapshot = build_self_knowledge_snapshot(settings, state)
    assert snapshot["product_name"] == PRODUCT_NAME
    for key in (
        "active_persona_id",
        "inference_profile",
        "inference_backend",
        "loaded",
        "model_alias",
        "context_size",
        "server_n_ctx",
        "front_lane_enabled",
        "decision_tier",
        "jev_availability",
        "laya_installed",
        "laya_warm",
        "laya_enabled",
        "voice_profile_id",
        "tts_engine",
        "dialogue_verbosity",
        "personality_preset",
        "output_language",
        "address_style",
        "shell",
        "vault_bound",
    ):
        assert key in SNAPSHOT_INCLUDE_KEYS
        assert key in snapshot
    assert snapshot["vault_bound"] is True
    assert snapshot["server_n_ctx"] == 8192
    assert snapshot["context_size"] == 16384
    rendered = snapshot_prompt_addendum(snapshot)
    assert "ANZU Superassistant" in rendered
    leaks = _forbidden_snapshot_leak(rendered)
    assert leaks == []
    blob = json.dumps(snapshot).lower()
    for forbidden in (
        "super-secret-token",
        "inference-secret",
        "front-secret",
        "voice-secret",
        "/home/owner/vault",
        "/opt/models/secret.gguf",
        "4321",
        "mcp_servers",
        "tool catalog",
    ):
        assert forbidden.lower() not in blob
        assert forbidden.lower() not in rendered.lower()


def test_snapshot_covers_profile_question(jarvis_env):
    settings = jarvis_env["settings"]
    assert snapshot_covers_question("What profile is loaded?", settings, jarvis_env["manager"].state) is True
    assert snapshot_covers_question("What is the TypeSafe API key?", settings) is False


@pytest.mark.asyncio
async def test_self_status_is_final_basic_from_snapshot(jarvis_env):
    settings = jarvis_env["settings"]
    settings.inference.profile = "fast"
    jarvis_env["manager"].state.loaded = True
    jarvis_env["manager"].state.profile = "fast"
    jarvis_env["manager"].state.alias = "qwen-fast"

    class Provider:
        async def chat_stream(self, messages, **kwargs):
            del kwargs
            joined = "\n".join(item.content or "" for item in messages)
            assert "ANZU Superassistant" in joined
            assert "qwen-fast" in joined or "fast" in joined
            assert "inference-secret" not in joined
            yield "The loaded profile is fast (qwen-fast)."

    reply = await generate_front_reply(
        "What profile is loaded?",
        settings=settings,
        provider=Provider(),
    )
    assert reply.action == "final_basic"
    assert worker_required(reply.action) is False
    assert "fast" in reply.text.lower()
    assert SAFE_ACK not in reply.text


def test_self_status_envelope_contains_snapshot_not_secrets(jarvis_env):
    settings = jarvis_env["settings"]
    settings.inference.api_key = "inference-secret"
    snapshot = build_self_knowledge_snapshot(settings, jarvis_env["manager"].state)
    messages = small_context_envelope(
        "What profile is loaded?",
        action_hint="final_basic",
        snapshot=snapshot,
        reply_shape="self_status",
    )
    joined = "\n".join(item.content for item in messages)
    assert "ANZU Superassistant" in joined
    assert _forbidden_snapshot_leak(joined) == []
    assert "inference-secret" not in joined


def test_self_status_allows_snapshot_numbers():
    snapshot = {"context_size": 16384, "product_name": PRODUCT_NAME}
    action, text, rejected = enforce_front_safety(
        "final_basic",
        "The configured context size is currently 16384.",
        user_text="What is the context size?",
        heuristic="final_basic",
        reply_shape="self_status",
        snapshot=snapshot,
    )
    assert rejected is False
    assert action == "final_basic"
    assert "16384" in text


def test_real_task_may_still_ack():
    assert classify_front_action("Refactor the auth module and run the tests") in {
        "handoff_notice",
        "ack_continue",
    }
    assert fallback_text_for_action("ack_continue", reply_shape="ack") == SAFE_ACK


@pytest.mark.asyncio
async def test_failed_self_status_front_falls_through_to_worker():
    reply = await generate_front_reply(
        "What profile is loaded?",
        settings=AppSettings(),
        provider=object(),
    )
    assert reply.action == "ack_continue"
    assert reply.text == ""
    assert "live self snapshot" not in (reply.text or "").lower()
    assert worker_required(reply.action) is True


@pytest.mark.asyncio
async def test_safety_rejected_self_status_falls_through_to_worker():
    class Unsafe:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "The configured context size is currently 16."

    reply = await generate_front_reply(
        "What profile is loaded?",
        settings=AppSettings(),
        provider=Unsafe(),
    )
    assert reply.action == "ack_continue"
    assert "live self snapshot" not in (reply.text or "").lower()
    assert worker_required(reply.action) is True


def test_self_status_rejects_digit_substring_of_snapshot_json():
    snapshot = {"context_size": 16384, "product_name": PRODUCT_NAME}
    action, text, rejected = enforce_front_safety(
        "final_basic",
        "The configured context size is currently 16.",
        user_text="What is the context size?",
        heuristic="final_basic",
        reply_shape="self_status",
        snapshot=snapshot,
    )
    assert rejected is True
    assert action == "ack_continue"
    assert text == ""


def test_coverage_does_not_call_load_settings_or_resolve_status(monkeypatch):
    monkeypatch.setattr(
        "app.config.load_settings",
        lambda: (_ for _ in ()).throw(AssertionError("load_settings")),
    )
    monkeypatch.setattr(
        "app.decision.tier.resolve_status",
        lambda: (_ for _ in ()).throw(AssertionError("resolve_status")),
    )
    monkeypatch.setattr(
        "app.licensing.lease.get_stored_lease",
        lambda: (_ for _ in ()).throw(AssertionError("lease")),
    )
    assert snapshot_covers_question("What profile is loaded?") is True
    assert snapshot_covers_question("What model of car should I buy?") is False
    assert snapshot_covers_question("what's your context on the Henderson case") is False
