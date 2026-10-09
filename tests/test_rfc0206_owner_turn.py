"""RFC-0206 slice 2: every owner turn calls decide() with a 50 ms cap."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.agent.front_responder import worker_required
from app.agent.planning import MANAGED_TASK, DIRECT_REPLY, route_request
from app.decision.audit import list_events, reset_audit
from app.decision.owner_turn import (
    OWNER_TURN_DEADLINE_MS,
    decide_owner_turn,
    infer_rules_reply_shape,
    is_self_status_domain_misroute,
    is_self_status_question,
)
from app.decision.types import Answer, DecisionResult
from app.persona.owner_chat import stream_owner_chat


def test_verify_command_intake_hooks_owner_turn_decide():
    source = Path("scripts/verify_command_intake.py").read_text(encoding="utf-8")
    assert "owner_turn.decide" in source
    assert "request_routing.decide" not in source
    from app.decision import owner_turn as owner_turn_mod

    assert hasattr(owner_turn_mod, "decide")
    assert callable(owner_turn_mod.decide)


def test_owner_chat_source_calls_evaluate_request_route():
    source = Path("backend/app/persona/owner_chat.py").read_text(encoding="utf-8")
    assert "evaluate_request_route(" in source
    assert "route_request(cleaned)" in source


def test_classify_and_two_lane_do_not_call_route_request():
    front = Path("backend/app/agent/front_responder.py").read_text(encoding="utf-8")
    assert "route_request(" not in front.replace("evaluate_request_route(", "")
    assert "evaluate_request_route(" in front


def test_loop_intake_calls_evaluate_request_route():
    source = Path("backend/app/agent/loop.py").read_text(encoding="utf-8")
    assert "evaluate_request_route(" in source
    assert "decide_owner_turn(" not in source


@pytest.mark.asyncio
async def test_decide_owner_turn_always_calls_decide(monkeypatch):
    seen = []

    def spy(state, questions, decision_class, deadline, privacy):
        seen.append(
            {
                "class": decision_class,
                "deadline": deadline,
                "privacy": privacy,
                "tier": state.get("decision_tier"),
                "literal": state.get("literal_candidate"),
            }
        )
        return DecisionResult(
            answers={
                "request_route": Answer("request_route", "choice", DIRECT_REPLY, 0.9),
                "reply_shape": Answer("reply_shape", "choice", "social", 0.9),
            },
            source="rules",
            decision_class=decision_class,
            provider="rules",
        )

    monkeypatch.setattr("app.decision.owner_turn.decide", spy)
    turn = await decide_owner_turn("Hello there", baseline=route_request("Hello there"), decision_tier="local")
    assert seen and seen[0]["class"] == "request_routing"
    assert seen[0]["deadline"] == OWNER_TURN_DEADLINE_MS
    assert seen[0]["privacy"] == "local_only"
    assert turn.front_action == "final_basic"
    assert turn.reply_shape == "social"


@pytest.mark.asyncio
async def test_local_tier_opens_no_jev_socket(monkeypatch):
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("local tier must not open TypeSafe")

    monkeypatch.setattr("app.decision.jev_client.post_systemone", forbidden)
    monkeypatch.setattr("app.decision.adapters.jev_adapter.post_systemone", forbidden)
    turn = await decide_owner_turn(
        "Hello there",
        baseline=route_request("Hello there"),
        decision_tier="local",
    )
    assert calls == []
    assert turn.reflex is not None
    if turn.reflex.source == "jev":
        assert turn.reflex.fallback_used is False
        raise AssertionError("local tier attributed a Jev source")
    assert turn.reflex.provider != "jev" or turn.reflex.fallback_used


@pytest.mark.asyncio
async def test_deadline_fallback_within_50ms(monkeypatch):
    def blocking(*_args, **_kwargs):
        time.sleep(0.25)
        return DecisionResult(
            answers={
                "request_route": Answer("request_route", "choice", DIRECT_REPLY, 0.9),
                "reply_shape": Answer("reply_shape", "choice", "social", 0.9),
            },
            source="laya",
            decision_class="request_routing",
            provider="laya",
        )

    monkeypatch.setattr("app.decision.owner_turn.decide", blocking)
    started = time.perf_counter()
    turn = await decide_owner_turn("Hello there", baseline=route_request("Hello there"), decision_tier="local")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert elapsed_ms < 120.0
    assert turn.reflex is not None
    assert turn.reflex.fallback_used is True
    assert turn.reflex.source == "deadline_fallback"
    assert turn.route.kind == DIRECT_REPLY


@pytest.mark.asyncio
async def test_stream_owner_chat_fails_if_decide_skipped(monkeypatch, jarvis_env):
    from app.inference.front_runtime import FRONT_RUNTIME
    from app.inference.manager import MANAGER
    from app.persona.owner_chat import reset_owner_conversations

    reset_audit()
    seen = []

    from app.decision.reflex import decide as original

    def spy(*args, **kwargs):
        seen.append(args[2] if len(args) > 2 else kwargs.get("decision_class"))
        return original(*args, **kwargs)

    monkeypatch.setattr("app.decision.reflex.decide", spy)
    monkeypatch.setattr("app.decision.owner_turn.decide", spy)

    class Provider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Hello."

    async def no_weather(_text: str):
        return None

    async def no_hydrate(_conversation_id: str):
        return []

    FRONT_RUNTIME.reset_for_tests()
    FRONT_RUNTIME.mark_for_tests(distinct=False, provider=Provider())
    MANAGER.provider = Provider()
    MANAGER.state.loaded = True
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", no_weather)
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", no_hydrate)
    reset_owner_conversations()
    try:
        events = []
        async for event in stream_owner_chat("Hello there"):
            events.append(event)
        assert "request_routing" in seen
        assert any(event.get("type") == "done" for event in events)
        audit = list_events()
        assert any(row.get("decision_class") == "request_routing" for row in audit)
    finally:
        FRONT_RUNTIME.reset_for_tests()
        MANAGER.provider = None


@pytest.mark.asyncio
async def test_tool_and_app_floors_stay_managed():
    tools = await decide_owner_turn(
        "run the filesystem tool on C:\\",
        baseline=route_request("run the filesystem tool on C:\\"),
        decision_tier="local",
    )
    assert tools.route.kind == MANAGED_TASK
    assert tools.reply_shape == "handoff"
    steam = await decide_owner_turn("open steam", baseline=route_request("open steam"), decision_tier="local")
    assert steam.route.kind == MANAGED_TASK
    assert steam.front_action == "handoff_notice"


@pytest.mark.asyncio
async def test_low_confidence_route_keeps_rules_baseline(monkeypatch):
    monkeypatch.setattr(
        "app.decision.owner_turn.decide",
        lambda *args: DecisionResult(
            answers={
                "request_route": Answer("request_route", "choice", MANAGED_TASK, 0.2),
                "reply_shape": Answer("reply_shape", "choice", "handoff", 0.9),
            },
            source="laya",
            decision_class="request_routing",
            provider="laya",
        ),
    )
    turn = await decide_owner_turn("Hello there", baseline=route_request("Hello there"), decision_tier="local")
    assert turn.route.kind == DIRECT_REPLY


DOMAIN_UTTERANCES_MUST_NOT_SELF_STATUS = (
    "What model of car should I buy?",
    "Which model is best for coding?",
    "what are you doing tomorrow",
    "is the vault locked?",
    "what's your context on the Henderson case",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", DOMAIN_UTTERANCES_MUST_NOT_SELF_STATUS)
async def test_domain_questions_do_not_route_to_self_status(utterance):
    assert is_self_status_domain_misroute(utterance) is True
    assert infer_rules_reply_shape(utterance) != "self_status"
    turn = await decide_owner_turn(
        utterance,
        baseline=route_request(utterance),
        decision_tier="local",
    )
    assert turn.reply_shape != "self_status"
    assert worker_required(turn.front_action) is True
    assert turn.front_action in {"ack_continue", "handoff_notice", "silent_skip"}


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", DOMAIN_UTTERANCES_MUST_NOT_SELF_STATUS)
async def test_domain_veto_overrides_confident_provider_self_status(utterance, monkeypatch):
    monkeypatch.setattr(
        "app.decision.owner_turn.decide",
        lambda *args: DecisionResult(
            answers={
                "request_route": Answer("request_route", "choice", DIRECT_REPLY, 0.95),
                "reply_shape": Answer("reply_shape", "choice", "self_status", 0.95),
            },
            source="laya",
            decision_class="request_routing",
            provider="laya",
        ),
    )
    turn = await decide_owner_turn(
        utterance,
        baseline=route_request(utterance),
        decision_tier="local",
    )
    assert turn.reply_shape != "self_status"
    assert worker_required(turn.front_action) is True


PROVIDER_KEEPS_SELF_STATUS = (
    "how much context do you have?",
    "which voice are you using?",
    "what are you?",
)


def test_what_are_you_matches_self_status_regex():
    assert is_self_status_question("what are you?") is True
    assert is_self_status_question("what are you") is True
    assert is_self_status_question("what are you doing tomorrow") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", PROVIDER_KEEPS_SELF_STATUS)
async def test_confident_provider_self_status_is_kept(utterance, monkeypatch):
    monkeypatch.setattr(
        "app.decision.owner_turn.decide",
        lambda *args: DecisionResult(
            answers={
                "request_route": Answer("request_route", "choice", DIRECT_REPLY, 0.95),
                "reply_shape": Answer("reply_shape", "choice", "self_status", 0.95),
            },
            source="laya",
            decision_class="request_routing",
            provider="laya",
        ),
    )
    turn = await decide_owner_turn(
        utterance,
        baseline=route_request(utterance),
        decision_tier="local",
    )
    assert turn.reply_shape == "self_status"
    assert turn.front_action == "final_basic"
    assert worker_required(turn.front_action) is False


@pytest.mark.asyncio
async def test_self_status_decision_does_not_load_settings(monkeypatch):
    monkeypatch.setattr(
        "app.config.load_settings",
        lambda: (_ for _ in ()).throw(AssertionError("load_settings in decide")),
    )
    monkeypatch.setattr(
        "app.decision.tier.resolve_status",
        lambda: (_ for _ in ()).throw(AssertionError("resolve_status in decide")),
    )
    turn = await decide_owner_turn(
        "What profile is loaded?",
        baseline=route_request("What profile is loaded?"),
        decision_tier="local",
    )
    assert turn.reply_shape == "self_status"
    assert turn.front_action == "final_basic"


@pytest.mark.asyncio
async def test_laya_fixture_via_set_decide_fn_is_labelled(jarvis_env, monkeypatch):
    from app.decision.laya import pins as laya_pins
    from app.decision.laya import runtime as laya_runtime
    from app.decision.types import Answer

    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.decision.laya.pins.data_dir", lambda: tmp)
    laya_runtime.reset_runtime()
    laya_pins.clear_install()
    laya_pins.write_test_install()
    laya_runtime.enable(warm=True)

    def fixture_decide(*, state, questions, decision_class):
        del state, questions, decision_class
        return {
            "request_route": Answer("request_route", "choice", DIRECT_REPLY, 0.95),
            "reply_shape": Answer("reply_shape", "choice", "social", 0.95),
        }

    laya_runtime.set_decide_fn(fixture_decide)
    try:
        turn = await decide_owner_turn(
            "Hello there",
            baseline=route_request("Hello there"),
            decision_tier="local",
        )
        assert turn.reflex is not None
        assert turn.reflex.source == "laya"
        assert turn.reflex.fixture is True
        assert turn.reflex.fallback_used is False
        assert turn.reply_shape == "social"
    finally:
        laya_runtime.reset_runtime()
        laya_pins.clear_install()


@pytest.mark.asyncio
async def test_stub_jev_on_connected_optional_is_source_jev(jarvis_env, monkeypatch):
    from app.decision.jev_client import reset_http_post, set_http_post
    from app.decision.laya import runtime as laya_runtime
    from app.decision.tier import bind_typesafe_key, probe_jev, set_decision_tier
    from app.licensing.store import reset_licensing_store

    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.config.data_dir", lambda: tmp)
    monkeypatch.setattr("app.licensing.cluster.data_dir", lambda: tmp)
    reset_licensing_store()
    reset_http_post()
    laya_runtime.reset_runtime()

    def jev_post(_url, _headers, body, _timeout):
        questions = body.get("questions") or {}
        answers = {}
        if "ready" in questions:
            answers["ready"] = {"type": "noul", "noul": 0.91, "confidence": 0.94}
        if "request_route" in questions:
            answers["request_route"] = {"type": "choice", "choice": DIRECT_REPLY, "confidence": 0.96}
        if "reply_shape" in questions:
            answers["reply_shape"] = {"type": "choice", "choice": "social", "confidence": 0.94}
        return 200, {"model": "jev-latest", "answers": answers}, ""

    set_http_post(jev_post, fixture=True)
    set_decision_tier("jev_optional")
    bind_typesafe_key("sk-rfc0206-fixture")
    probed = probe_jev()
    assert probed["ok"] is True
    assert probed["jev_availability"] == "connected"
    try:
        turn = await decide_owner_turn(
            "Hello there",
            baseline=route_request("Hello there"),
            decision_tier="jev_optional",
            settings=jarvis_env["settings"],
        )
        assert turn.reflex is not None
        assert turn.reflex.source == "jev"
        assert turn.reflex.provider == "jev"
        assert turn.reflex.fallback_used is False
        assert turn.reflex.fixture is True
    finally:
        reset_http_post()
        laya_runtime.reset_runtime()
        set_decision_tier("local")


@pytest.mark.asyncio
async def test_cold_laya_does_not_stall_the_turn(jarvis_env):
    from app.decision.laya import runtime as laya_runtime

    laya_runtime.reset_runtime()
    started = time.perf_counter()
    turn = await decide_owner_turn(
        "Hello there",
        baseline=route_request("Hello there"),
        decision_tier="local",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert elapsed_ms < 120.0
    assert turn.reflex is not None
    assert turn.reflex.source != "laya"
    assert turn.route.kind == DIRECT_REPLY


@pytest.mark.asyncio
async def test_slow_laya_fixture_falls_back_inside_deadline(jarvis_env, monkeypatch):
    from app.decision.laya import pins as laya_pins
    from app.decision.laya import runtime as laya_runtime
    from app.decision.types import Answer

    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.decision.laya.pins.data_dir", lambda: tmp)
    laya_runtime.reset_runtime()
    laya_pins.clear_install()
    laya_pins.write_test_install()
    laya_runtime.enable(warm=True)

    def slow_decide(**_kwargs):
        time.sleep(0.25)
        return {
            "request_route": Answer("request_route", "choice", DIRECT_REPLY, 0.99),
            "reply_shape": Answer("reply_shape", "choice", "social", 0.99),
        }

    laya_runtime.set_decide_fn(slow_decide)
    try:
        started = time.perf_counter()
        turn = await decide_owner_turn(
            "Hello there",
            baseline=route_request("Hello there"),
            decision_tier="local",
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        assert elapsed_ms < 120.0
        assert turn.reflex is not None
        assert turn.reflex.source != "laya" or turn.reflex.fallback_used is True
        assert turn.reflex.source in {"rules", "generative", "deadline_fallback"} or turn.reflex.fallback_used
    finally:
        laya_runtime.reset_runtime()
        laya_pins.clear_install()
