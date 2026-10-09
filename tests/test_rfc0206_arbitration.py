"""RFC-0206 slice 3: arbitration replaces the hardcoded merge policy."""

from __future__ import annotations

from app.agent.front_responder import (
    apply_disposition,
    infer_arbitration_disposition,
    merge_consecutive_assistant_turns,
    merge_front_and_worker,
)
from app.decision.types import Answer, DecisionResult


def test_provider_keep_front_drops_novel_worker(monkeypatch):
    def forced(*_args, **_kwargs):
        return DecisionResult(
            answers={"disposition": Answer("disposition", "choice", "keep_front", 0.99)},
            source="laya",
            decision_class="arbitration",
            provider="laya",
        )

    monkeypatch.setattr("app.decision.surfaces.decide", forced)
    merged = merge_front_and_worker(
        "On it. I'll check the details.",
        "Mild rain later, sir.",
        "ack_continue",
        user_message="what is the weather",
        reply_shape="ack",
    )
    assert merged == "On it. I'll check the details."
    assert "Mild rain" not in merged


def test_provider_append_novel_keeps_new_sentence(monkeypatch):
    def forced(*_args, **_kwargs):
        return DecisionResult(
            answers={"disposition": Answer("disposition", "choice", "append_novel", 0.99)},
            source="laya",
            decision_class="arbitration",
            provider="laya",
        )

    monkeypatch.setattr("app.decision.surfaces.decide", forced)
    merged = merge_front_and_worker(
        "On it. I'll check the details.",
        "Mild rain later, sir.",
        "ack_continue",
        user_message="what is the weather",
        reply_shape="ack",
    )
    assert merged.startswith("On it.")
    assert "Mild rain later, sir." in merged
    assert "Deeper result" not in merged


def test_literal_guard_forces_keep_front(monkeypatch):
    def forced(*_args, **_kwargs):
        return DecisionResult(
            answers={"disposition": Answer("disposition", "choice", "keep_worker", 0.99)},
            source="laya",
            decision_class="arbitration",
            provider="laya",
        )

    monkeypatch.setattr("app.decision.surfaces.decide", forced)
    merged = merge_front_and_worker(
        "ready",
        "I can start with the short version while I check the details.",
        "final_basic",
        user_message="Say only the word ready",
        reply_shape="literal",
    )
    assert merged == "ready"


def test_append_novel_degrades_when_worker_only_restates():
    front = "On it. I'll check the details."
    worker = "On it — I will check the details."
    text = apply_disposition("append_novel", front, worker)
    assert text == front


def test_merge_consecutive_assistant_turns_uses_arbitration_helper():
    turns = merge_consecutive_assistant_turns(
        [
            {"role": "user", "content": "Check the weather"},
            {"role": "assistant", "content": "On it."},
            {"role": "assistant", "content": "Mild rain later, sir."},
        ]
    )
    assert [item["role"] for item in turns] == ["user", "assistant"]
    assert "On it." in turns[-1]["content"]
    assert "Mild rain later" in turns[-1]["content"]
    assert "Deeper result" not in turns[-1]["content"]


def test_rules_disposition_for_correction_is_keep_worker():
    assert (
        infer_arbitration_disposition(
            "The meeting is at 3.",
            "The meeting was moved to 4:30, and it's in the north conference room.",
        )
        == "keep_worker"
    )


def test_one_sided_merge_skips_provider(monkeypatch):
    monkeypatch.setattr(
        "app.decision.surfaces.arbitrate_front_and_worker",
        lambda **_k: (_ for _ in ()).throw(AssertionError("no provider")),
    )
    assert merge_front_and_worker("", "Worker only.", "ack_continue") == "Worker only."
    assert merge_front_and_worker("Front only.", "", "ack_continue") == "Front only."
    assert merge_front_and_worker("", "Worker.", "silent_skip") == "Worker."
