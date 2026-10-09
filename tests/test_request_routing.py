import asyncio
import time

import pytest

from app.agent import request_routing
from app.agent.planning import route_request, MANAGED_TASK, DIRECT_REPLY
from app.decision.owner_turn import OWNER_TURN_DEADLINE_MS
from app.decision.types import Answer, DecisionResult


def _laya_route(kind: str, shape: str = "ack") -> DecisionResult:
    return DecisionResult(
        answers={
            "request_route": Answer("request_route", "choice", kind, 0.95),
            "reply_shape": Answer("reply_shape", "choice", shape, 0.95),
        },
        source="laya",
        decision_class="request_routing",
        provider="laya",
    )


@pytest.mark.asyncio
async def test_intake_uses_bounded_provider_before_returning_parser(monkeypatch):
    seen = []

    def decide(state, questions, decision_class, deadline, privacy):
        seen.append((state, questions, decision_class, deadline, privacy))
        return _laya_route(MANAGED_TASK, "handoff")

    monkeypatch.setattr("app.decision.owner_turn.decide", decide)
    result = await request_routing.evaluate_request_route("hello", route_request("hello"))
    assert result.route.kind == MANAGED_TASK
    assert seen[0][2] == "request_routing"
    assert seen[0][3] == OWNER_TURN_DEADLINE_MS
    assert {q.id for q in seen[0][1]} == {"request_route", "reply_shape"}
    assert len(seen[0][1][0].choices) == 3


@pytest.mark.asyncio
async def test_encoder_cannot_drop_explicit_action(monkeypatch):
    monkeypatch.setattr(
        "app.decision.owner_turn.decide",
        lambda *args: _laya_route(DIRECT_REPLY, "social"),
    )
    result = await request_routing.evaluate_request_route("open steam", route_request("open steam"))
    assert result.route.kind == MANAGED_TASK


@pytest.mark.asyncio
async def test_deadline_does_not_block_event_loop(monkeypatch):
    def slow(*_args):
        time.sleep(0.4)
        raise RuntimeError("slow encoder")

    monkeypatch.setattr("app.decision.owner_turn._decide_sync", slow)
    baseline = route_request("hello")
    started = time.perf_counter()
    task = asyncio.create_task(request_routing.evaluate_request_route("hello", baseline))
    await asyncio.sleep(0.02)
    assert not task.done()
    assert (await task).route == baseline
    assert time.perf_counter() - started < 0.3


@pytest.mark.asyncio
async def test_missing_provider_preserves_parser(monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("not installed")

    monkeypatch.setattr("app.decision.owner_turn._decide_sync", unavailable)
    baseline = route_request("open steam")
    assert (await request_routing.evaluate_request_route("open steam", baseline)).route == baseline


def test_default_is_fast_q6_and_never_silent_27b(tmp_path, monkeypatch):
    from app.config import InferenceSettings
    from app.inference import profiles

    monkeypatch.setattr(profiles, "models_dir", lambda: tmp_path)
    monkeypatch.setattr(profiles, "qwen38_9b_profile", lambda: profiles.PROFILES["balanced"])
    settings = InferenceSettings()
    assert settings.profile == "fast"
    assert settings.context_size == 16384
    assert profiles.preferred_startup_profile() == "fast"
    assert profiles.preferred_startup_profile("fast") == "fast"
    expert = tmp_path / profiles.EXPERT_DIR / profiles.PROFILES["expert"].filename
    expert.parent.mkdir(parents=True)
    expert.write_bytes(b"fixture")
    resolved = profiles.resolve_profile("fast")
    assert resolved.quant == "Q6_K"
    assert resolved.family == "9b-abliterated"
    assert resolved.thinking is False
