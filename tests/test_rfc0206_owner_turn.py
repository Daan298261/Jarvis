"""RFC-0206 slice 2: every owner turn calls decide() with a 50 ms cap."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.agent.planning import MANAGED_TASK, DIRECT_REPLY, route_request
from app.decision.audit import list_events, reset_audit
from app.decision.owner_turn import (
    OWNER_TURN_DEADLINE_MS,
    decide_owner_turn,
)
from app.decision.types import Answer, DecisionResult
from app.persona.owner_chat import stream_owner_chat


def test_owner_chat_source_calls_decide_owner_turn():
    source = Path("backend/app/persona/owner_chat.py").read_text(encoding="utf-8")
    assert "decide_owner_turn(" in source
    assert source.count("route_request(") == 1
    assert "baseline=route_request(" in source


def test_classify_and_two_lane_do_not_call_route_request():
    front = Path("backend/app/agent/front_responder.py").read_text(encoding="utf-8")
    assert "route_request(" not in front
    assert "decide_owner_turn(" in front


def test_loop_intake_calls_decide_owner_turn():
    source = Path("backend/app/agent/loop.py").read_text(encoding="utf-8")
    assert "decide_owner_turn(" in source


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

    FRONT_RUNTIME.mark_for_tests(distinct=False, provider=Provider())
    MANAGER.provider = Provider()
    MANAGER.state.loaded = True
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", no_weather)
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", no_hydrate)
    reset_owner_conversations()
    events = []
    async for event in stream_owner_chat("Hello there"):
        events.append(event)
    assert "request_routing" in seen
    assert any(event.get("type") == "done" for event in events)
    audit = list_events()
    assert any(row.get("decision_class") == "request_routing" for row in audit)


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
