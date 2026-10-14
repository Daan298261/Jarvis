"""RFC-0218 S1: persona_intent_switch decision class inside decide_owner_turn."""

from __future__ import annotations

import threading
import time

import pytest

from app.agent.planning import route_request
from app.config import AppSettings
from app.decision import PersonaTurnContext
from app.decision.owner_turn import OWNER_TURN_DEADLINE_MS, decide_owner_turn, resolve_persona_context
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

    settings = AppSettings()
    ctx = resolve_persona_context(PersonaTurnContext(current="anzu"), settings)
    _decide_sync("warm up", route_request("warm up"), "local", settings, None, "warm", ctx)


@pytest.fixture(autouse=True)
def frozen_reflex_clock(monkeypatch):
    """Inject a frozen clock into Reflex so elapsed time reads 0 ms against the
    unchanged 50 ms budget: semantics tests can't flip into deadline_fallback
    under CI load. Budget/deadline behaviour has its own tests below."""
    from types import SimpleNamespace

    monkeypatch.setattr("app.decision.reflex.time", SimpleNamespace(perf_counter=lambda: 0.0))


def _sync_turn(text: str, current: str, **kw):
    """The owner-turn worker body, minus the outer wall-clock wait_for."""
    from app.decision.owner_turn import _decide_sync

    settings = AppSettings()
    ctx = resolve_persona_context(PersonaTurnContext(current=current, **kw), settings)
    return _decide_sync(text, route_request(text), "local", settings, None, "sync", ctx)


async def _turn(text: str, current: str = "anzu", **kw):
    # Semantics tests run the worker body under the frozen Reflex clock. The real
    # wall-clock path (decide_owner_turn + wait_for) is covered by the budget,
    # deadline and settings tests, which call decide_owner_turn directly.
    return _sync_turn(text, current, **kw)


async def _owner_turn(text: str, current: str = "anzu", **kw):
    """Real path: decide_owner_turn with its 50 ms wait_for."""
    return await decide_owner_turn(
        text,
        baseline=route_request(text),
        decision_tier="local",
        settings=AppSettings(),
        persona=PersonaTurnContext(current=current, **kw),
    )


@pytest.mark.asyncio
async def test_one_decide_per_turn_carries_persona_question(monkeypatch):
    from app.decision import owner_turn

    calls = []
    real = owner_turn.decide

    def spy(state, questions, decision_class, *a, **kw):
        calls.append((decision_class, [q.id for q in questions]))
        return real(state, questions, decision_class, *a, **kw)

    monkeypatch.setattr(owner_turn, "decide", spy)
    turn = await _turn("Anzu, write me a script")
    assert len(calls) == 1
    decision_class, qids = calls[0]
    assert decision_class == "request_routing" and decision_class in REFLEX_DECISION_CLASSES
    assert decision_class not in POLICY_HARDENED_CLASSES
    assert qids == ["request_route", "reply_shape", "persona_intent"]
    assert turn.persona_intent.reflex is turn.reflex


@pytest.mark.asyncio
async def test_explicit_and_lock_settled_before_decide(monkeypatch):
    from app.decision import owner_turn

    seen = []
    real = owner_turn.decide

    def spy(state, questions, decision_class, *a, **kw):
        seen.append([q.id for q in questions])
        return real(state, questions, decision_class, *a, **kw)

    monkeypatch.setattr(owner_turn, "decide", spy)
    await _turn("Enki, write me a script", current="anzu")
    await _turn("write me a script", current="anzu", locked=True)
    assert len(seen) == 2 and all("persona_intent" not in q for q in seen)


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

    from app.decision import owner_turn

    real = owner_turn.decide

    def low(state, questions, decision_class, *a, **kw):
        result = real(state, questions, decision_class, *a, **kw)
        answers = dict(result.answers)
        answers["persona_intent"] = Answer("persona_intent", "choice", "enki", 0.5)
        return DecisionResult(
            answers=answers, source="laya", decision_class=decision_class, provider="laya"
        )

    monkeypatch.setattr(owner_turn, "decide", low)
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


@pytest.mark.parametrize("persona_id", ["enki", "anzu", "bragi"])
def test_same_persona_named_is_address_not_pin(persona_id):
    assert OWNER_TURN_DEADLINE_MS == 50.0  # budget unchanged; only the clock is injected
    label = CATALOG[persona_id].label
    chat = _sync_turn(f"{label}, thanks", current=persona_id)
    assert chat.persona_intent.to == persona_id
    assert chat.persona_intent.reason == "already_active"
    assert not chat.persona_intent.switch
    task = _sync_turn(f"{label}, research the history of rome", current=persona_id)
    assert task.persona_intent.reason == "intent"
    assert task.persona_intent.to == ("nabu" if persona_id != "nabu" else persona_id)


@pytest.mark.asyncio
async def test_same_persona_named_with_matching_intent_stays():
    turn = await _turn("Enki, write me a script", current="enki")
    assert turn.persona_intent.to == "enki", (turn.persona_intent.as_dict(), turn.reflex and (turn.reflex.source, turn.reflex.fallback_reason, turn.reflex.answers.get("persona_intent")))
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
    assert turn.persona_intent.to == "enki", (turn.persona_intent.as_dict(), turn.reflex and (turn.reflex.source, turn.reflex.fallback_reason, turn.reflex.answers.get("persona_intent")))


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
        del state, decision_class
        return {
            q.id: Answer(q.id, "choice", "nabu" if q.id == "persona_intent" else q.choices[0], 0.95)
            for q in questions
        }

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
async def test_persona_decision_measured_inside_budget(monkeypatch):
    """Times the real decision path (the worker that runs decide + persona)."""
    from app.decision import owner_turn

    spent: list[float] = []
    real = owner_turn._decide_sync

    def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            return real(*args, **kwargs)
        finally:
            spent.append((time.perf_counter() - started) * 1000.0)

    monkeypatch.setattr(owner_turn, "_decide_sync", timed)
    for text in ("write me a script", "thanks", "plan my mission for tomorrow"):
        turn = await _owner_turn(text)
        assert turn.persona_intent.reason != "deadline_fallback"
    assert len(spent) == 3
    assert max(spent) < OWNER_TURN_DEADLINE_MS, spent


@pytest.mark.asyncio
async def test_decision_path_never_loads_settings_and_slow_load_cannot_breach_deadline(monkeypatch):
    from app import config

    loads: list[int] = []

    def slow_load():
        loads.append(1)
        time.sleep(0.2)  # 4x the 50 ms cap, if it were ever on the path
        return AppSettings()

    monkeypatch.setattr(config, "load_settings", slow_load)
    settings = AppSettings()
    settings.named_personas.active_id = "anzu"
    started = time.perf_counter()
    turn = await decide_owner_turn(
        "write me a script", baseline=route_request("write me a script"), settings=settings
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert loads == []
    assert turn.persona_intent.reason == "intent" and turn.persona_intent.to == "enki"
    assert turn.reflex is not None and turn.reflex.source != "deadline_fallback"
    assert elapsed_ms < 200.0, elapsed_ms


@pytest.mark.asyncio
async def test_missing_settings_is_reported_on_decision_not_defaulted(monkeypatch, caplog):
    from app import config

    def must_not_load():
        raise AssertionError("load_settings on the decision path")

    monkeypatch.setattr(config, "load_settings", must_not_load)
    with caplog.at_level("WARNING", logger="jarvis.decision.owner_turn"):
        turn = await decide_owner_turn("write me a script", baseline=route_request("write me a script"))
    assert turn.persona_intent.reason == "settings_unavailable"
    assert turn.persona_intent.to == "" and not turn.persona_intent.switch
    assert turn.route.kind == route_request("write me a script").kind
    assert any("no settings supplied" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_deadline_fallback_stays(monkeypatch):
    gate = threading.Event()

    def blocking(*args, **kwargs):
        gate.wait(5)
        raise RuntimeError("released")

    monkeypatch.setattr("app.decision.owner_turn.decide", blocking)
    try:
        turn = await _owner_turn("write me a script", current="anzu")
    finally:
        gate.set()
    assert turn.persona_intent.to == "anzu"
    assert turn.persona_intent.reason == "deadline_fallback"
    assert turn.persona_intent.decision_source == "deadline_fallback"
