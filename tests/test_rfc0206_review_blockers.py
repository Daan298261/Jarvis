"""Behavioral regressions for the held RFC-0206 build."""
import asyncio
import time

import pytest

from app.agent.front_responder import SAFE_ACK, generate_front_reply, run_two_lane_chat
from app.agent.self_knowledge import snapshot_covers_question
from app.config import AppSettings
from app.decision import owner_turn
from app.decision.types import Answer, DecisionResult


def decision(shape="self_status", confidence=.95):
    return DecisionResult(answers={"request_route": Answer("request_route", "choice", "direct_reply", .95), "reply_shape": Answer("reply_shape", "choice", shape, confidence)}, source="laya", provider="laya", decision_class="request_routing")


@pytest.mark.parametrize("question", ["what's your context on the Henderson case", "How can ANZU help with the Henderson case?", "Which voice did the witness hear?", "What profile fits the suspect?", "Explain context windows in transformers", "What is your model of the crime?", "What is your context size and what do you know about Henderson?"])
def test_domain_questions_are_not_snapshot_readings(question):
    assert not snapshot_covers_question(question)


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["what's your context on the Henderson case", "How can ANZU help with the Henderson case?", "Which voice did the witness hear?", "What profile fits the suspect?"])
async def test_real_two_lane_runs_worker_for_domain_questions(question, monkeypatch):
    monkeypatch.setattr(owner_turn, "decide", lambda *args: decision())
    envelopes = []
    class Front:
        async def chat_stream(self, messages, **kwargs):
            envelopes.extend(str(message.content) for message in messages)
            yield SAFE_ACK
    monkeypatch.setattr("app.agent.front_responder.front_provider", lambda settings: Front())
    called = []
    async def worker():
        called.append(True)
        yield "The case record needs review; no facts have been verified yet."
    events = [e async for e in run_two_lane_chat(question, settings=AppSettings(), worker_stream=worker)]
    assert called == [True]
    assert "worker_response_started" in [e["type"] for e in events]
    assert "case record" in events[-1]["text"]
    assert not any("Use only the self-knowledge snapshot" in text for text in envelopes)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("question, expected", [("Say only the word ready", "ready"), ("just say open steam", "open steam")])
async def test_literal_is_exact_even_with_front_disabled(question, expected, enabled):
    settings = AppSettings()
    settings.front_responder.enabled = enabled
    called = []
    async def worker():
        called.append(True)
        yield "Wrong worker response"
    events = [e async for e in run_two_lane_chat(question, settings=settings, worker_stream=worker)]
    assert events[-1]["text"] == expected
    assert called == []


def test_embedded_literal_does_not_hide_real_command():
    assert owner_turn.extract_literal_candidate("Open Steam then say only the word ready") == ""


@pytest.mark.asyncio
async def test_low_confidence_shape_does_not_suppress_worker(monkeypatch):
    monkeypatch.setattr(owner_turn, "decide", lambda *args: decision("social", .2))
    turn = await owner_turn.decide_owner_turn("Explain the Henderson case evidence")
    assert turn.front_action in {"ack_continue", "handoff_notice"}


@pytest.mark.asyncio
async def test_self_status_holding_line_runs_worker(monkeypatch):
    monkeypatch.setattr(owner_turn, "decide", lambda *args: decision())
    class Front:
        async def chat_stream(self, messages, **kwargs): yield SAFE_ACK
    reply = await generate_front_reply("What profile is loaded?", settings=AppSettings(), provider=Front())
    assert reply.action == "ack_continue"
    assert reply.text != SAFE_ACK


def test_warm_laya_does_not_probe_jev(tmp_path, monkeypatch):
    from app.decision import reflex
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr(reflex.laya_runtime, "is_ready", lambda: True)
    monkeypatch.setattr(reflex.laya_adapter, "available", lambda **kwargs: (True, ""))
    monkeypatch.setattr(reflex.laya_adapter, "decide", lambda **kwargs: decision("social"))
    monkeypatch.setattr(reflex.jev_adapter, "available", lambda **kwargs: (_ for _ in ()).throw(AssertionError("Cold Jev probe before warm Laya")))
    monkeypatch.setattr(reflex.quartermaster, "select_provider_order", lambda *args, **kwargs: ["laya", "jev"])
    result = reflex.decide({"user_message": "Hello"}, owner_turn.OWNER_TURN_QUESTIONS, "request_routing", 50, "allow_cloud", use_cache=False)
    assert result.provider == "laya"


@pytest.mark.asyncio
async def test_late_provider_records_one_timeout_result(tmp_path, monkeypatch):
    from app.decision import reflex, audit, metrics
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    audit.reset_audit()
    metrics.reset_metrics()
    monkeypatch.setattr(reflex.laya_runtime, "is_ready", lambda: True)
    monkeypatch.setattr(reflex.laya_adapter, "available", lambda **kwargs: (True, ""))
    def slow(**kwargs):
        time.sleep(.12)
        return decision("social")
    monkeypatch.setattr(reflex.laya_adapter, "decide", slow)
    monkeypatch.setattr(reflex.quartermaster, "select_provider_order", lambda *args, **kwargs: ["laya"])
    turn = await owner_turn.decide_owner_turn("Hello")
    assert turn.reflex.source == "deadline_fallback"
    await asyncio.sleep(.2)
    events = [e for e in audit.list_events(80) if e.get("request_id") == turn.reflex.request_id]
    assert len(events) == 1
    assert events[0]["kind"] == "reflex_deadline_fallback"
    assert sum(row["hits"] for row in metrics.snapshot()["decision_classes"]) == 1
