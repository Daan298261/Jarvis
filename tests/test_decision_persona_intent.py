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


def _frozen_clock() -> float:
    """Injected clock: elapsed time reads 0 ms against the unchanged 50 ms budget."""
    return 0.0


async def _turn(text: str, current: str = "anzu", **kw):
    # Semantics tests: public decide_owner_turn with the frozen clock injected, so
    # CI load can't flip a turn into deadline_fallback. Budget/deadline tests use
    # _owner_turn (wall clock, real wait_for).
    return await decide_owner_turn(
        text,
        baseline=route_request(text),
        decision_tier="local",
        settings=AppSettings(),
        persona=PersonaTurnContext(current=current, **kw),
        clock=_frozen_clock,
    )


async def _owner_turn(text: str, current: str = "anzu", **kw):
    """Real path: decide_owner_turn on the wall clock with its 50 ms wait_for."""
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
        calls.append((decision_class, {q.id: q.decision_class for q in questions}))
        return real(state, questions, decision_class, *a, **kw)

    monkeypatch.setattr(owner_turn, "decide", spy)
    turn = await _turn("Anzu, write me a script")
    assert len(calls) == 1  # exactly one decide() for routing + persona
    decision_class, qclasses = calls[0]
    assert decision_class == "request_routing"
    assert list(qclasses) == ["request_route", "reply_shape", "persona_intent"]
    assert qclasses["persona_intent"] == "persona_intent_switch"
    assert "persona_intent_switch" in REFLEX_DECISION_CLASSES
    assert "persona_intent_switch" not in POLICY_HARDENED_CLASSES
    assert turn.persona_intent.to == "enki" and turn.persona_intent.reflex is turn.reflex


def test_unlisted_question_class_is_rejected():
    from dataclasses import replace

    from app.decision.reflex import decide
    from app.decision.surfaces import persona_intent_question

    bad = replace(persona_intent_question(), decision_class="not_a_class")
    with pytest.raises(ValueError, match="unlisted decision_class"):
        decide({"user_message": "hi"}, [bad], "request_routing", 50.0)


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
    assert intent.to == "enki"
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
        "write me a script",
        baseline=route_request("write me a script"),
        settings=settings,
        clock=_frozen_clock,
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
        clock=_frozen_clock,
    )
    assert tuned.persona_intent.to == "enki"


@pytest.mark.asyncio
@pytest.mark.parametrize("persona_id", ["enki", "anzu", "bragi"])
async def test_same_persona_named_is_address_not_pin(persona_id):
    assert OWNER_TURN_DEADLINE_MS == 50.0  # budget unchanged; only the clock is injected
    label = CATALOG[persona_id].label
    chat = await _turn(f"{label}, thanks", current=persona_id)
    assert chat.persona_intent.to == persona_id
    assert chat.persona_intent.reason == "already_active"
    assert not chat.persona_intent.switch
    task = await _turn(f"{label}, research the history of rome", current=persona_id)
    assert task.persona_intent.reason == "intent"
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
        "write me a script",
        baseline=route_request("write me a script"),
        settings=settings,
        clock=_frozen_clock,
    )
    assert turn.persona_intent.reason == "no_current_persona"


@pytest.mark.asyncio
async def test_current_persona_read_from_settings_store():
    settings = AppSettings()
    settings.named_personas.active_id = "nabu"
    turn = await decide_owner_turn(
        "write me a script",
        baseline=route_request("write me a script"),
        settings=settings,
        clock=_frozen_clock,
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


class _StepClock:
    """Controlled clock: each read advances exactly ``step_s``."""

    def __init__(self, step_s: float):
        self.step_s = step_s
        self.now = 0.0
        self.reads = 0

    def __call__(self) -> float:
        value = self.now
        self.now += self.step_s
        self.reads += 1
        return value


@pytest.mark.asyncio
async def test_persona_decision_measured_inside_budget():
    """Deterministic elapsed time on a controlled clock against the 50 ms budget."""
    for text in ("write me a script", "thanks", "plan my mission for tomorrow"):
        clock = _StepClock(0.001)  # 1 ms per read
        turn = await decide_owner_turn(
            text,
            baseline=route_request(text),
            decision_tier="local",
            settings=AppSettings(),
            persona=PersonaTurnContext(current="anzu"),
            clock=clock,
        )
        elapsed_ms = (clock.now - clock.step_s) * 1000.0  # last read minus the first
        assert turn.persona_intent.reason != "deadline_fallback"
        assert turn.persona_intent.reflex is turn.reflex
        assert 0.0 < elapsed_ms < OWNER_TURN_DEADLINE_MS


@pytest.mark.asyncio
async def test_real_path_wait_for_deadline_is_50ms(monkeypatch):
    import asyncio

    timeouts: list[float] = []
    real_wait_for = asyncio.wait_for

    async def spy(aw, timeout):
        timeouts.append(timeout)
        return await real_wait_for(aw, timeout)

    monkeypatch.setattr(asyncio, "wait_for", spy)
    await _owner_turn("write me a script")
    assert timeouts == [0.05]
    assert timeouts[0] * 1000.0 == OWNER_TURN_DEADLINE_MS == 50.0


@pytest.mark.asyncio
async def test_slow_settings_load_resolves_before_decision_window(monkeypatch):
    """Real 50 ms cut-off (no injected clock). The owner-turn caller loads settings
    (slowly) before calling decide_owner_turn; the decision window opens only after
    that load returned and never calls or awaits it."""
    from app import config
    from app.decision import owner_turn

    events: list[tuple[str, float]] = []

    def slow_load():
        events.append(("load_start", time.perf_counter()))
        time.sleep(0.2)  # 4x the 50 ms cap
        settings = AppSettings()
        settings.named_personas.active_id = "anzu"
        events.append(("load_end", time.perf_counter()))
        return settings

    real_sync = owner_turn._decide_sync

    def window(*args, **kwargs):
        events.append(("window_open", time.perf_counter()))
        try:
            return real_sync(*args, **kwargs)
        finally:
            events.append(("window_close", time.perf_counter()))

    monkeypatch.setattr(config, "load_settings", slow_load)
    monkeypatch.setattr(owner_turn, "_decide_sync", window)
    settings = config.load_settings()  # what the owner-chat/loop caller does first
    turn = await decide_owner_turn(
        "write me a script", baseline=route_request("write me a script"), settings=settings
    )
    names = [name for name, _ in events]
    # window_close may land after a real 50 ms cut-off; the order up to it may not vary.
    assert names[:3] == ["load_start", "load_end", "window_open"]
    assert names.count("load_start") == 1
    stamps = dict(events)
    assert stamps["load_end"] <= stamps["window_open"]
    assert turn.persona_intent.current == "anzu"  # persona read from the loaded settings


@pytest.mark.asyncio
async def test_missing_settings_is_reported_on_decision_not_defaulted(monkeypatch, caplog):
    from app import config

    def must_not_load():
        raise AssertionError("load_settings on the decision path")

    monkeypatch.setattr(config, "load_settings", must_not_load)
    with caplog.at_level("WARNING", logger="jarvis.decision.owner_turn"):
        turn = await decide_owner_turn(
            "write me a script", baseline=route_request("write me a script"), clock=_frozen_clock
        )
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


@pytest.mark.asyncio
async def test_injected_clock_enforces_the_same_50ms_budget():
    ticks = iter([0.0] + [1.0] * 1000)  # second read onward: 1 s after start

    turn = await decide_owner_turn(
        "write me a script",
        baseline=route_request("write me a script"),
        settings=AppSettings(),
        persona=PersonaTurnContext(current="anzu"),
        clock=lambda: next(ticks),
    )
    assert turn.persona_intent.reason == "deadline_fallback"
    assert turn.persona_intent.to == "anzu"


def test_every_production_caller_passes_settings():
    """Fails if any backend/app call of the owner-turn entry points omits settings
    (persona state would then report settings_unavailable on a live turn)."""
    import ast
    from pathlib import Path

    entry_points = {"decide_owner_turn", "evaluate_request_route"}
    app_root = Path(__file__).resolve().parents[1] / "backend" / "app"
    found, missing = [], []
    for path in app_root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in entry_points:
                continue
            where = f"{path.relative_to(app_root)}:{node.lineno}"
            found.append(where)
            kw = {k.arg: k.value for k in node.keywords}
            value = kw.get("settings")
            if value is None or (isinstance(value, ast.Constant) and value.value is None):
                missing.append(where)
    assert len(found) >= 5  # request_routing + owner_chat + loop + 2x front_responder
    assert missing == []
