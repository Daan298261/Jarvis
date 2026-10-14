"""RFC-0218 S2: backend persona switch + spoken switch line + same-turn start in owner chat."""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.front_responder import FrontReply
from app.agent.planning import route_request
from app.decision import PersonaTurnContext
from app.decision.owner_turn import OWNER_TURN_DEADLINE_MS
from app.persona.chat_delivery import pending_chat_tts, reset_chat_delivery
from app.persona.named_persona import CATALOG
from app.persona.owner_chat import reset_owner_conversations, stream_owner_chat
from app.tts import persona_speech
from app.tts.persona_speech import SpeechRefused, persona_switch_line

FRONT_TEXT = "On it, writing that now."


@pytest.fixture(autouse=True)
def _warm_decision():
    # Cold imports on the first turn can exceed the 50 ms owner-turn cap (the
    # deadline-fallback path, covered in S1). Warm them once.
    from app.decision.owner_turn import _decide_sync

    _decide_sync("warm up", route_request("warm up"), "local", None, None, "warm", PersonaTurnContext(current="anzu"))


@pytest.fixture
def owner(jarvis_env, monkeypatch):
    """Owner chat with a fake front lane and in-memory persona store; records call order."""
    settings = jarvis_env["settings"]
    settings.named_personas.active_id = "anzu"
    settings.named_personas.auto_switch_locked = False
    calls: list[tuple[str, str]] = []
    missing_packs: set[str] = set()

    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.persona.named_persona.load_settings", lambda: settings)
    monkeypatch.setattr("app.persona.named_persona.save_settings", lambda _s: None)
    monkeypatch.setattr("app.tts.persona_speech.load_settings", lambda: settings)
    monkeypatch.setattr("app.persona.chat_delivery.load_settings", lambda: settings)
    monkeypatch.setattr("app.persona.owner_chat.load_settings", lambda: settings)
    monkeypatch.setattr(
        "app.persona.named_persona.pack_status",
        lambda pid: "install_required" if pid in missing_packs else "ok",
    )
    monkeypatch.setattr(
        "app.persona.named_persona.set_active_voice_profile_id",
        lambda pid: calls.append(("activate", pid)),
    )
    real_resolve = persona_speech.resolve_speaking_voice

    def _resolve(**kw):
        voice = real_resolve(**kw)
        calls.append(("resolve_voice", voice.persona_id))
        return voice

    monkeypatch.setattr("app.tts.persona_speech.resolve_speaking_voice", _resolve)

    async def fake_front(*_a, **_k):
        return FrontReply(
            action="final_basic", text=FRONT_TEXT, chunks=[FRONT_TEXT], model="front",
            first_text_ms=1.0, complete_ms=1.0,
        )

    monkeypatch.setattr("app.persona.owner_chat.generate_front_reply", fake_front)
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", AsyncMock(return_value=None))
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", AsyncMock(return_value=[]))
    reset_chat_delivery()
    reset_owner_conversations()
    yield {"settings": settings, "calls": calls, "missing_packs": missing_packs}
    reset_chat_delivery()
    reset_owner_conversations()


async def _run(text: str) -> list[tuple[float, dict]]:
    events = []
    async for event in stream_owner_chat(text):
        events.append((time.perf_counter(), event))
    # Let the fire-and-forget switch line run to completion.
    pending = list(persona_speech._switch_announcements)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return events


def _of(events, kind):
    return [e for _t, e in events if e.get("type") == kind]


def _roster_voice(persona_id: str) -> str:
    return CATALOG[persona_id].voice_profile_id


@pytest.mark.asyncio
async def test_intent_switch_emits_once_activates_then_speaks_in_new_voice(owner, monkeypatch):
    from app.agent import request_routing

    decided = []
    real_route = request_routing.evaluate_request_route

    async def _record(*a, **k):
        turn = await real_route(*a, **k)
        decided.append(turn.persona_intent)
        return turn

    monkeypatch.setattr("app.agent.request_routing.evaluate_request_route", _record)
    events = await _run("Anzu, write me a script")
    switched = _of(events, "persona_switched")
    assert len(switched) == 1
    event = switched[0]
    assert (event["from"], event["to"], event["reason"]) == ("anzu", "enki", "intent")
    (intent,) = decided
    assert (event["decision_source"], event["confidence"]) == (intent.decision_source, intent.confidence)
    assert event["confidence"] >= owner["settings"].decision.persona_intent_confidence_floor
    assert event["conversation_id"] == _of(events, "start")[0]["conversation_id"]
    assert owner["settings"].named_personas.active_id == "enki"
    calls = owner["calls"]
    first_activate = calls.index(("activate", _roster_voice("enki")))
    first_resolve = next(i for i, c in enumerate(calls) if c[0] == "resolve_voice")
    assert first_activate < first_resolve
    assert all(persona == "enki" for kind, persona in calls if kind == "resolve_voice")
    voice = persona_speech.resolve_speaking_voice(lane="front")
    assert voice.persona_id == "enki"
    assert voice.profile_id == _roster_voice("enki")


@pytest.mark.asyncio
async def test_switch_line_queued_on_front_lane_in_new_persona_voice(owner, monkeypatch):
    await _run("Anzu, write me a script")
    line = persona_switch_line("enki", owner["settings"])
    items = [item for item in pending_chat_tts() if item["text"] == line]
    assert len(items) == 1
    assert items[0]["persona_id"] == "enki"
    assert items[0]["voice_profile_id"] == _roster_voice("enki")
    assert items[0]["lane"] == "front"
    # Playback synthesizes the queued line through speak_text in the new voice.
    seen = {}

    async def fake_synth(text, *, voice_profile_id, **_k):
        seen["text"], seen["voice"] = text, voice_profile_id
        return SimpleNamespace(engine_id="kokoro")

    monkeypatch.setattr("app.tts.persona_speech.synthesize_speech_result", fake_synth)
    await persona_speech.speak_text(items[0]["text"], lane="front")
    assert seen == {"text": line, "voice": _roster_voice("enki")}


@pytest.mark.asyncio
async def test_explicit_name_switch_reports_explicit_name(owner):
    events = await _run("Bragi, write me a poem")
    (event,) = _of(events, "persona_switched")
    assert (event["from"], event["to"], event["reason"]) == ("anzu", "bragi", "explicit_name")
    assert event["decision_source"] == "rules"
    assert event["confidence"] == 1.0
    assert owner["settings"].named_personas.active_id == "bragi"


@pytest.mark.asyncio
async def test_work_starts_same_turn_on_new_persona_without_confirmation(owner):
    events = await _run("Anzu, write me a script")
    kinds = [e["type"] for _t, e in events]
    assert kinds.index("persona_switched") < kinds.index("delta") < kinds.index("done")
    assert "".join(e["text"] for e in _of(events, "delta")) == FRONT_TEXT
    assert not {"confirmation_required", "approval_required", "persona_switch_failed"} & set(kinds)
    # The turn's own reply is voiced by the new persona too.
    reply_items = [item for item in pending_chat_tts() if FRONT_TEXT.rstrip(".") in item["text"]]
    assert reply_items and all(item["persona_id"] == "enki" for item in reply_items)


@pytest.mark.asyncio
async def test_first_text_not_delayed_by_switch(owner):
    events = await _run("Anzu, write me a script")
    t_switch = next(t for t, e in events if e["type"] == "persona_switched")
    t_first_text = next(t for t, e in events if e["type"] == "delta")
    assert (t_first_text - t_switch) * 1000.0 < OWNER_TURN_DEADLINE_MS


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["thanks", "how are you"])
async def test_no_switch_no_event_no_speech(owner, text):
    events = await _run(text)
    assert not _of(events, "persona_switched")
    assert not _of(events, "persona_switch_failed")
    assert _of(events, "done")
    assert owner["settings"].named_personas.active_id == "anzu"
    assert not [c for c in owner["calls"] if c[0] == "activate"]
    assert not [i for i in pending_chat_tts() if i["text"] == persona_switch_line("enki", owner["settings"])]


@pytest.mark.asyncio
async def test_lock_on_blocks_intent_switch(owner):
    owner["settings"].named_personas.auto_switch_locked = True
    events = await _run("Anzu, write me a script")
    assert not _of(events, "persona_switched")
    assert owner["settings"].named_personas.active_id == "anzu"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [SpeechRefused("no neural voice", persona_id="enki"), RuntimeError("tts down")])
async def test_switch_line_failure_never_blocks_or_fails_turn(owner, monkeypatch, caplog, error):
    async def boom(*_a, **_k):
        raise error

    # Only the switch line goes through chat_delivery's module attribute; the turn's
    # own reply uses owner_chat's binding and still delivers.
    monkeypatch.setattr("app.persona.chat_delivery.publish_owner_text", boom)
    with caplog.at_level(logging.WARNING, logger="app.tts.persona_speech"):
        events = await _run("Anzu, write me a script")
    assert len(_of(events, "persona_switched")) == 1
    (done,) = _of(events, "done")
    assert done["text"] == FRONT_TEXT
    assert "persona switch line not spoken" in caplog.text


@pytest.mark.asyncio
async def test_hanging_switch_line_does_not_hold_the_turn(owner, monkeypatch):
    never = asyncio.Event()

    async def hang(*_a, **_k):
        await never.wait()

    monkeypatch.setattr("app.persona.chat_delivery.publish_owner_text", hang)
    events = []
    async for event in stream_owner_chat("Anzu, write me a script"):
        events.append((time.perf_counter(), event))
    assert _of(events, "done")
    pending = list(persona_speech._switch_announcements)
    assert len(pending) == 1 and not pending[0].done()
    pending[0].cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    assert not persona_speech._switch_announcements


@pytest.mark.asyncio
async def test_bind_failure_keeps_persona_and_reports(owner):
    owner["missing_packs"].add(_roster_voice("enki"))
    events = await _run("Anzu, write me a script")
    assert not _of(events, "persona_switched")
    (failed,) = _of(events, "persona_switch_failed")
    assert (failed["to"], failed["error"]) == ("enki", "install_required")
    assert owner["settings"].named_personas.active_id == "anzu"
    assert not [i for i in pending_chat_tts() if i["text"] == persona_switch_line("enki", owner["settings"])]
    assert _of(events, "done")


@pytest.mark.asyncio
async def test_approval_and_harm_veto_unaffected_by_switch(owner, monkeypatch, jarvis_env):
    from app.decision.adapters import rules
    from app.policy.action_gate import gate_tool_call
    from app.policy.authorize import AuthorizationResult
    from app.policy.levels import AutonomyLevel
    from app.security.red_scenarios import HARM
    from app.tools.base import RiskLevel

    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.policy.approval_grant.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr(
        "app.policy.reversibility_gate.authorize",
        lambda *a, **k: AuthorizationResult(True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "terminal.run"),
    )
    monkeypatch.setattr(
        "app.policy.action_gate.decide",
        lambda *a, **k: type("R", (), {"answers": {}, "fallback_used": True, "provider": "generative"})(),
    )

    def policy():
        gate = gate_tool_call("terminal", action="run", arguments={"command": "rm -rf scratch"}, risk=RiskLevel.IRREVERSIBLE)
        veto = rules.decide(state={"user_message": "format c:"}, questions=[HARM], decision_class="harm_veto")
        return gate.allowed, veto.hard_rule, veto.answers["cancel"].value

    before = policy()
    await _run("Anzu, write me a script")
    assert owner["settings"].named_personas.active_id == "enki"
    after = policy()
    assert before == after == (False, True, "cancel")
