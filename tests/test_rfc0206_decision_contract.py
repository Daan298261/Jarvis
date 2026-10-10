"""RFC-0206 slice 1: decision contract, rules adapter, arbitration fixture table."""

from __future__ import annotations

from app.agent.front_responder import (
    apply_disposition,
    infer_arbitration_disposition,
    merge_front_and_worker,
)
from app.agent.planning import DIRECT_LOOKUP, DIRECT_REPLY, MANAGED_TASK, route_request
from app.decision.owner_turn import (
    OWNER_TURN_DEADLINE_MS,
    extract_literal_candidate,
    infer_rules_reply_shape,
)
from app.decision.reflex import decide
from app.decision.surfaces import ARBITRATION_CHOICES, arbitrate_front_and_worker
from app.decision.types import POLICY_HARDENED_CLASSES, REFLEX_DECISION_CLASSES


ARBITRATION_FIXTURES = (
    {
        "id": "paraphrase_dropped",
        "front": (
            "Those black bars are just letterboxing. "
            "Tell me your screen resolution and I'll match the viewport."
        ),
        "worker": (
            "Those black bars you're seeing are just my viewport padding. "
            "If they bother you, tell me your screen resolution."
        ),
        "disposition": "keep_front",
        "action": "ack_continue",
    },
    {
        "id": "novel_worker_kept",
        "front": "On it. I'll check the details.",
        "worker": "Mild rain later, sir.",
        "disposition": "append_novel",
        "action": "ack_continue",
    },
    {
        "id": "correction_keep_worker",
        "front": "The meeting is at 3.",
        "worker": "The meeting was moved to 4:30, and it's in the north conference room.",
        "disposition": "keep_worker",
        "action": "ack_continue",
    },
)


def test_arbitration_is_a_reflex_class_and_not_policy_hardened():
    assert "arbitration" in REFLEX_DECISION_CLASSES
    assert "arbitration" not in POLICY_HARDENED_CLASSES
    assert "request_routing" in REFLEX_DECISION_CLASSES


def test_literal_extractor_closed_patterns():
    assert extract_literal_candidate("Say only the word ready") == "ready"
    assert extract_literal_candidate("say only Ready") == "Ready"
    assert extract_literal_candidate("reply with only ok") == "ok"
    assert extract_literal_candidate("just say yes") == "yes"
    assert extract_literal_candidate('reply with exactly "all set now"') == "all set now"
    assert extract_literal_candidate("Refactor the auth module and run the tests") == ""


def test_explicit_action_and_weather_floors():
    assert infer_rules_reply_shape("open steam") == "handoff"
    assert infer_rules_reply_shape("run the filesystem tool on C:\\") == "handoff"
    assert infer_rules_reply_shape("what is the weather in dinteloord, tomorrow") == "ack"
    assert infer_rules_reply_shape("Hello there") == "social"
    assert infer_rules_reply_shape("When is my meeting tomorrow?") == "ack"
    assert infer_rules_reply_shape("Say only the word ready") == "literal"
    assert infer_rules_reply_shape("What profile is loaded?") == "self_status"
    assert infer_rules_reply_shape("what are you?") == "self_status"
    assert infer_rules_reply_shape("do it") == "clarify"
    assert infer_rules_reply_shape("Refactor this architecture and run pytest") == "handoff"


def test_rules_adapter_answers_both_owner_turn_questions_without_laya_or_jev():
    result = decide(
        {
            "user_message": "Hello there",
            "baseline_route": route_request("Hello there").kind,
            "literal_candidate": "",
            "decision_tier": "local",
        },
        {
            "request_route": {
                "type": "choice",
                "choices": [DIRECT_REPLY, DIRECT_LOOKUP, MANAGED_TASK],
                "question": "route",
            },
            "reply_shape": {
                "type": "choice",
                "choices": ["literal", "self_status", "social", "ack", "clarify", "handoff"],
                "question": "shape",
            },
        },
        "request_routing",
        OWNER_TURN_DEADLINE_MS,
        "local_only",
    )
    assert result.answers["request_route"].value == DIRECT_REPLY
    assert result.answers["reply_shape"].value == "social"
    assert result.source in {"rules", "generative", "deadline_fallback"}
    assert result.provider in {"rules", "generative"}
    assert result.source != "jev"
    assert result.source != "laya" or result.fixture is True


def test_arbitration_fixture_table_rules_match_today():
    for row in ARBITRATION_FIXTURES:
        disposition = infer_arbitration_disposition(
            row["front"],
            row["worker"],
            front_action=row["action"],
        )
        assert disposition == row["disposition"], row["id"]
        merged = apply_disposition(disposition, row["front"], row["worker"])
        assert "Deeper result" not in merged
        if disposition == "keep_front":
            assert merged == row["front"]
        elif disposition == "keep_worker":
            assert merged == row["worker"]
            assert "4:30" in merged
        else:
            assert merged.startswith(row["front"])
            assert "Mild rain later, sir." in merged


def test_final_basic_empty_worker_does_not_call_arbitration(monkeypatch):
    called = []

    def boom(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("arbitration must not run when the worker is empty")

    monkeypatch.setattr("app.decision.surfaces.arbitrate_front_and_worker", boom)
    assert merge_front_and_worker("Hi, sir.", "", "final_basic") == "Hi, sir."
    assert called == []


def test_arbitration_decide_returns_typed_disposition():
    result = arbitrate_front_and_worker(
        user_message="Check the weather",
        front_text="On it. I'll check the details.",
        worker_text="Mild rain later, sir.",
        front_action="ack_continue",
        reply_shape="ack",
        decision_tier="local",
    )
    assert result.decision_class == "arbitration"
    assert result.answers["disposition"].value in ARBITRATION_CHOICES
    assert result.answers["disposition"].value == "append_novel"
    assert result.source in {"rules", "generative", "deadline_fallback"}
