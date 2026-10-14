"""RFC-0218 S1: persona_intent_switch decision class inside decide_owner_turn."""

from __future__ import annotations

import threading

import pytest

from app.agent.planning import route_request
from app.config import AppSettings
from app.decision import PersonaTurnContext
from app.decision.owner_turn import OWNER_TURN_DEADLINE_MS, decide_owner_turn
from app.decision.types import POLICY_HARDENED_CLASSES, REFLEX_DECISION_CLASSES, Answer
from app.persona.named_persona import CATALOG

FIXTURES = [
    "Anzu, write me a script",
    "write a python script that renames files",
    "thanks",
    "how are you",
    "Enki, fix this bug",
    "Bragi, write me a poem",
    "plan my mission for tomorrow",
]


@pytest.fixture(autouse=True)
def _warm_imports():
    # Cold imports on the first turn can exceed the 50 ms owner-turn cap, which is
    # the (separately tested) deadline-fallback path. Warm them once.
    from app.decision.owner_turn import _decide_sync

    _decide_sync("warm up", route_request("warm up"), "local", None, None, "warm", PersonaTurnContext(current="anzu"))


async def _turn(text: str, current: str = "anzu", **kw):
    return await decide_owner_turn(
        text,
        baseline=route_request(text),
        decision_tier="local",
        persona=PersonaTurnContext(current=current, **kw),
    )


def test_class_registered_reflex_not_policy_hardened():
    assert "persona_intent_switch" in REFLEX_DECISION_CLASSES
    assert "persona_intent_switch" not in POLICY_HARDENED_CLASSES


@pytest.mark.asyncio
async def test_anzu_write_me_a_script_switches_to_enki():
    turn = await _turn("Anzu, write me a script")
    intent = turn.persona_intent
    assert intent is not None
    assert intent.current == "anzu"
    assert intent.to == "enki", (intent.as_dict(), turn.reflex and turn.reflex.fallback_reason)
    assert intent.switch and intent.reason == "intent"
    assert intent.confidence >= 0.75


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["thanks", "how are you", "thank you!", "hello there", "ok cool"])
@pytest.mark.parametrize("current", ["anzu", "enki"])
async def test_chit_chat_stays_including_after_switch(text, current):
    turn = await _turn(text, current=current)
    assert turn.persona_intent.to == current
    assert not turn.persona_intent.switch


@pytest.mark.asyncio
async def test_hysteresis_sequence_never_flips_back():
    first = await _turn("Anzu, write me a script", current="anzu")
    assert first.persona_intent.to == "enki"
    second = await _turn("thanks", current=first.persona_intent.to)
    assert second.persona_intent.to == "enki"


@pytest.mark.asyncio
@pytest.mark.parametrize("persona_id", sorted(CATALOG))
async def test_explicit_roster_name_wins_regardless_of_intent(persona_id):
    current = "nabu" if persona_id != "nabu" else "anzu"
    label = CATALOG[persona_id].label
    turn = await _turn(f"{label}, write me a script", current=current)
    assert turn.persona_intent.to == persona_id
    assert turn.persona_intent.reason == "explicit_name"
    assert turn.persona_intent.confidence == 1.0
    # Explicit name beats lock too (precedence 1 > 2).
    locked = await _turn(f"{label}, write me a script", current=current, locked=True)
    assert locked.persona_intent.to == persona_id


@pytest.mark.asyncio
@pytest.mark.parametrize("text", FIXTURES)
async def test_lock_on_stays_for_every_non_explicit_fixture(text):
    turn = await _turn(text.split(", ", 1)[-1], current="anzu", locked=True)
    assert turn.persona_intent.to == "anzu"
    assert turn.persona_intent.reason == "locked"


@pytest.mark.asyncio
async def test_lock_read_from_settings(monkeypatch):
    settings = AppSettings()
    settings.named_personas.auto_switch_locked = True
    turn = await decide_owner_turn(
        "write me a script", baseline=route_request("write me a script"), settings=settings
    )
    assert turn.persona_intent.to == "anzu"
    assert turn.persona_intent.reason == "locked"


@pytest.mark.asyncio
async def test_below_confidence_floor_stays(monkeypatch):
    from app.decision.types import DecisionResult

    def low(state, questions, decision_class, deadline, privacy, **kw):
        assert decision_class == "persona_intent_switch"
        return DecisionResult(
            answers={"persona_intent": Answer("persona_intent", "choice", "enki", 0.5)},
            source="laya",
            decision_class=decision_class,
            provider="laya",
        )

    monkeypatch.setattr("app.decision.surfaces.decide", low)
    turn = await _turn("write me a script")
    assert turn.persona_intent.to == "anzu" and turn.persona_intent.reason == "below_floor"
    settings = AppSettings()
    settings.decision.persona_intent_confidence_floor = 0.4
    tuned = await decide_owner_turn(
        "write me a script",
        baseline=route_request("write me a script"),
        settings=settings,
        persona=PersonaTurnContext(current="anzu", locked=False),
    )
    assert tuned.persona_intent.to == "enki"


@pytest.mark.asyncio
@pytest.mark.parametrize("persona_id", ["enki", "anzu", "bragi"])
async def test_same_persona_named_is_address_not_pin(persona_id):
    label = CATALOG[persona_id].label
    chat = await _turn(f"{label}, thanks", current=persona_id)
    assert chat.persona_intent.to == persona_id
    assert chat.persona_intent.reason == "already_active"
    assert not chat.persona_intent.switch
    task = await _turn(f"{label}, research the history of rome", current=persona_id)
    assert task.persona_intent.to == ("nabu" if persona_id != "nabu" else persona_id)


@pytest.mark.asyncio
async def test_same_persona_named_with_matching_intent_stays():
    turn = await _turn("Enki, write me a script", current="enki")
    assert turn.persona_intent.to == "enki"
    assert turn.persona_intent.reason == "already_active"


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["", "not_a_persona"])
async def test_no_current_persona_is_reported_not_defaulted(current):
    turn = await _turn("write me a script", current=current)
    intent = turn.persona_intent
    assert intent.reason == "no_current_persona"
    assert intent.current == "" and intent.to == ""
    assert not intent.switch


@pytest.mark.asyncio
async def test_no_current_persona_from_settings_store():
    settings = AppSettings()
    settings.named_personas.active_id = ""
    turn = await decide_owner_turn(
        "write me a script", baseline=route_request("write me a script"), settings=settings
    )
    assert turn.persona_intent.reason == "no_current_persona"


@pytest.mark.asyncio
async def test_current_persona_read_from_settings_store():
    settings = AppSettings()
    settings.named_personas.active_id = "nabu"
    turn = await decide_owner_turn(
        "write me a script", baseline=route_request("write me a script"), settings=settings
    )
    assert turn.persona_intent.current == "nabu"
    assert turn.persona_intent.to == "enki"


@pytest.mark.asyncio
async def test_fixture_provider_persona_respected_over_rules(jarvis_env, monkeypatch):
    from app.decision.laya import pins as laya_pins
    from app.decision.laya import runtime as laya_runtime

    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.decision.laya.pins.data_dir", lambda: tmp)
    laya_runtime.reset_runtime()
    laya_pins.clear_install()
    laya_pins.write_test_install()
    laya_runtime.enable(warm=True)

    def fixture_decide(*, state, questions, decision_class):
        del state
        if decision_class == "persona_intent_switch":
            return {"persona_intent": Answer("persona_intent", "choice", "nabu", 0.95)}
        return {q.id: Answer(q.id, "choice", q.choices[0], 0.95) for q in questions}

    laya_runtime.set_decide_fn(fixture_decide)
    try:
        # Rules baseline would pick enki; the provider's nabu must stand.
        turn = await _turn("write me a script")
        assert turn.persona_intent.to == "nabu"
        assert turn.persona_intent.decision_source == "laya"
        assert turn.persona_intent.reason == "intent"
        # Explicit and locked still override the provider.
        assert (await _turn("Enki, write me a script")).persona_intent.to == "enki"
        assert (await _turn("write me a script", locked=True)).persona_intent.to == "anzu"
    finally:
        laya_runtime.reset_runtime()
        laya_pins.clear_install()


@pytest.mark.asyncio
async def test_decision_within_reflex_budget():
    import time

    started = time.perf_counter()
    turn = await _turn("write me a script")
    assert turn.persona_intent is not None
    assert turn.persona_intent.reflex is not None
    assert turn.persona_intent.reflex.decision_class == "persona_intent_switch"
    # Structural: the class runs inside the owner-turn wait_for (50 ms cap).
    assert OWNER_TURN_DEADLINE_MS == 50.0
    assert (time.perf_counter() - started) < 5.0


@pytest.mark.asyncio
async def test_deadline_fallback_stays(monkeypatch):
    gate = threading.Event()

    def blocking(*args, **kwargs):
        gate.wait(5)
        raise RuntimeError("released")

    monkeypatch.setattr("app.decision.surfaces.decide", blocking)
    try:
        turn = await _turn("write me a script", current="anzu")
    finally:
        gate.set()
    assert turn.persona_intent.to == "anzu"
    assert turn.persona_intent.reason == "deadline_fallback"
    assert turn.persona_intent.decision_source == "deadline_fallback"
