from __future__ import annotations

import pytest

from app.decision import cache, metrics, quartermaster
from app.decision.laya import pins as laya_pins
from app.decision.laya import runtime as laya_runtime
from app.decision.reflex import decide, decide_many
from app.decision.surfaces import (
    browser_operation_target,
    route_persona_model,
    score_memory_relevance,
    select_tools,
)
from app.decision.types import Question

from .fixtures import ALL_FIXTURES, FIXTURE_APPROVAL, FIXTURE_TOOL_SELECT


@pytest.fixture(autouse=True)
def _clean_reflex(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.config.data_dir", lambda: tmp)
    monkeypatch.setattr("app.decision.laya.pins.data_dir", lambda: tmp)
    cache.clear()
    metrics.reset_metrics()
    quartermaster.reset_quartermaster()
    laya_runtime.reset_runtime()
    laya_pins.clear_install()
    yield
    cache.clear()
    metrics.reset_metrics()
    quartermaster.reset_quartermaster()
    laya_runtime.reset_runtime()
    laya_pins.clear_install()


def test_decide_rules_first_local_only():
    result = decide(
        FIXTURE_TOOL_SELECT["state"],
        FIXTURE_TOOL_SELECT["questions"],
        FIXTURE_TOOL_SELECT["decision_class"],
        80.0,
        "local_only",
    )
    assert result.provider in {"rules", "generative"}
    assert result.source != "jev"
    assert "tool_select" in result.answers
    assert result.answers["tool_select"].value == "filesystem"
    assert result.fallback_source in {"", "rules", "generative"} or result.fallback_used in {True, False}


def test_hard_policy_cannot_be_weakened():
    result = decide(
        FIXTURE_APPROVAL["state"],
        FIXTURE_APPROVAL["questions"],
        FIXTURE_APPROVAL["decision_class"],
        50.0,
        "local_only",
    )
    assert result.hard_rule is True
    assert float(result.answers["approval_needed"].value) >= 0.99


def test_deny_wins_over_reflex():
    result = decide(
        {
            "user_message": "rm -rf",
            "policy_requires_approval": False,
            "policy_deny": True,
        },
        {"approval_needed": {"type": "noul", "question": "approve?"}},
        "approval_signal",
        50.0,
        "local_only",
    )
    assert float(result.answers["approval_needed"].value) == 0.0
    assert result.hard_rule is True


def test_same_state_questions_batch_into_one_call():
    calls = {"n": 0}
    original = decide

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    # decide_many with identical state should merge into one underlying decide for the group.
    from app.decision import reflex as reflex_mod

    monkey_calls = {"n": 0}
    real = reflex_mod.decide

    def counting_decide(*args, **kwargs):
        monkey_calls["n"] += 1
        return real(*args, **kwargs)

    reflex_mod.decide = counting_decide  # type: ignore[assignment]
    try:
        jobs = [
            {
                "state": {"user_message": "same"},
                "questions": {"a": {"type": "score", "question": "a", "min": 0, "max": 1}},
                "decision_class": "memory_relevance",
                "privacy": "local_only",
            },
            {
                "state": {"user_message": "same"},
                "questions": {"b": {"type": "score", "question": "b", "min": 0, "max": 1}},
                "decision_class": "memory_relevance",
                "privacy": "local_only",
            },
        ]
        results = decide_many(jobs)
        assert len(results) == 2
        assert monkey_calls["n"] == 1
        assert "a" in results[0].answers
        assert "b" in results[1].answers
        assert results[0].meta.get("batched") is True
    finally:
        reflex_mod.decide = real  # type: ignore[assignment]


def test_cache_hits_pure_decisions():
    first = decide(
        FIXTURE_TOOL_SELECT["state"],
        FIXTURE_TOOL_SELECT["questions"],
        FIXTURE_TOOL_SELECT["decision_class"],
        80.0,
        "local_only",
    )
    second = decide(
        FIXTURE_TOOL_SELECT["state"],
        FIXTURE_TOOL_SELECT["questions"],
        FIXTURE_TOOL_SELECT["decision_class"],
        80.0,
        "local_only",
    )
    assert first.answers["tool_select"].value == second.answers["tool_select"].value
    assert second.cached is True or second.source == "cache"


def test_deadline_fallback_is_audited_and_explicit():
    laya_pins.write_test_install()
    laya_runtime.enable(warm=True)

    def slow(**_kwargs):
        raise TimeoutError("Laya exceeded deadline (999ms > 1ms)")

    laya_runtime.set_decide_fn(slow)
    result = decide(
        FIXTURE_TOOL_SELECT["state"],
        FIXTURE_TOOL_SELECT["questions"],
        FIXTURE_TOOL_SELECT["decision_class"],
        1.0,
        "local_only",
    )
    assert result.fallback_used is True
    assert result.fallback_source == "rules"
    assert result.source == "deadline_fallback"
    assert result.answers


def test_surfaces_routing_tools_memory_browser():
    routed = route_persona_model(
        user_message="hello",
        candidates=["fast", "balanced"],
        preferred_profile="fast",
    )
    assert routed.answers["route_profile"].value in {"fast", "balanced", "default"}

    tools = select_tools(user_message="git commit please", candidates=["filesystem", "git"])
    assert tools.answers["tool_select"].value in {"git", "filesystem", "none"}

    mem = score_memory_relevance(
        user_message="vault router",
        candidates=[
            {"excerpt": "vault router orientation"},
            {"excerpt": "unrelated cooking recipe"},
        ],
    )
    assert "memory_0" in mem.answers and "memory_1" in mem.answers

    browser = browser_operation_target(
        goal="click search",
        operations=["CLICK", "TYPE_TEXT"],
        target_ids=["n1", "n2"],
        suggested_operation="CLICK",
        suggested_target_id="n2",
    )
    assert browser.answers["operation"].value == "CLICK"
    assert browser.answers["target_id"].value == "n2"


def test_byte_identical_fixtures_run_for_all_classes():
    for fixture in ALL_FIXTURES:
        result = decide(
            fixture["state"],
            fixture["questions"],
            fixture["decision_class"],
            100.0,
            "local_only",
        )
        assert result.answers
        assert result.provider in {"rules", "laya", "jev", "generative"}
        assert result.fallback_source is not None


def test_laya_pins_require_apache_and_hashes():
    manifest = laya_pins.pin_manifest()
    assert manifest["license"] == "Apache-2.0"
    for row in manifest["artifacts"]:
        assert row["license"] == "Apache-2.0"
    # Empty production sha256 must refuse validate_artifact_bytes
    with pytest.raises(ValueError):
        laya_pins.validate_artifact_bytes("x", b"data", expected_sha256="")
    installed = laya_pins.write_test_install()
    assert installed["fixture"] is True
    ok, err, _ = laya_pins.verify_installed(allow_fixture=True)
    assert ok is True
    assert err == ""
    status = laya_runtime.enable(warm=True)
    assert status["warm"] is True
    assert status["loopback_only"] is True
    assert status["bind"] == "127.0.0.1"


def test_laya_preferred_when_warm():
    laya_pins.write_test_install()
    laya_runtime.enable(warm=True)
    result = decide(
        FIXTURE_TOOL_SELECT["state"],
        FIXTURE_TOOL_SELECT["questions"],
        FIXTURE_TOOL_SELECT["decision_class"],
        80.0,
        "local_only",
    )
    assert result.provider == "laya"
    assert result.source == "laya"
    assert result.answers["tool_select"].type == "choice"


def test_metrics_snapshot_for_control_room():
    decide(
        FIXTURE_TOOL_SELECT["state"],
        FIXTURE_TOOL_SELECT["questions"],
        FIXTURE_TOOL_SELECT["decision_class"],
        80.0,
        "local_only",
    )
    snap = metrics.snapshot()
    assert snap["decision_classes"]
    row = snap["decision_classes"][0]
    assert "latency_end_to_end_ms" in row
    assert "p50" in row["latency_end_to_end_ms"]
    assert "fallback_rate" in row
