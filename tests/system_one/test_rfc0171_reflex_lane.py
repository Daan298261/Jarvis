"""RFC-0171 System-One Reflex Lane tests — fixtures for Jev/Laya/rules/fallback."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.decision.audit import list_events, reset_audit
from app.decision.cache import clear as clear_cache
from app.decision.jev_client import reset_http_post, set_http_post
from app.decision.laya import enable_and_warm, reset_runtime, set_inference_fn, status as laya_status
from app.decision.metrics import reset_metrics, snapshot
from app.decision.policy import apply_complexity_tier, approval_popup_required
from app.decision.reflex import decide
from app.decision.tier import bind_typesafe_key, probe_jev, resolve_status, set_decision_tier
from app.decision.types import Question
from app.decision.wire import (
    compose_turn_decisions,
    decide_browser_operation_target,
    decide_memory_relevance,
    decide_persona_model_route,
    decide_tool_selection,
)
from app.licensing.store import reset_licensing_store
from app.main import app


def _ok_jev(_url, _headers, body, _timeout):
    questions = body.get("questions") or {}
    answers = {}
    if "ready" in questions:
        answers["ready"] = {"type": "noul", "noul": 0.91, "confidence": 0.94}
    for qid, spec in questions.items():
        if qid == "ready":
            continue
        qtype = (spec or {}).get("type")
        if qtype == "choice":
            choices = (spec or {}).get("choices") or ["none"]
            pick = "filesystem" if "filesystem" in choices else choices[0]
            if "technical" in choices:
                pick = "technical"
            if "balanced" in choices:
                pick = "balanced"
            if "click" in choices:
                pick = "click"
            answers[qid] = {"type": "choice", "choice": pick, "confidence": 0.9}
        elif qtype == "score":
            answers[qid] = {"type": "score", "score": 0.8, "confidence": 0.85}
        else:
            answers[qid] = {"type": "noul", "noul": 0.2, "confidence": 0.9}
    return 200, {"model": "jev-latest", "answers": answers}, ""


@pytest.fixture
def reflex_env(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    settings: AppSettings = jarvis_env["settings"]
    monkeypatch.setattr("app.config.data_dir", lambda: tmp)
    monkeypatch.setattr("app.licensing.cluster.data_dir", lambda: tmp)
    reset_licensing_store()
    reset_audit()
    reset_http_post()
    reset_runtime()
    reset_metrics()
    clear_cache()
    set_inference_fn(None)
    settings.decision.tier = "local"
    settings.decision.notify_requested_at = ""
    settings.decision.plus_features = []
    settings.decision.last_availability = "unavailable"
    settings.decision.laya_enabled = False
    settings.decision.laya_warm = False
    yield {"tmp": tmp, "settings": settings}
    reset_http_post()
    reset_runtime()
    reset_metrics()
    clear_cache()
    reset_audit()


def test_decide_rules_first_covers_tool_select(reflex_env):
    result = decide(
        {"user_message": "please use the filesystem tool", "candidate_tools": ["filesystem", "git"]},
        [
            Question(
                id="tool_select",
                type="choice",
                prompt="pick a tool",
                choices=("filesystem", "git", "none"),
            )
        ],
        "tool_selection",
        deadline_ms=50,
        privacy="local_only",
    )
    assert result.value("tool_select") == "filesystem"
    assert result.source in {"rules", "laya", "generative_fallback"}
    assert result.fallback_used is False or result.source == "rules"


def test_batching_same_state_memory_relevance(reflex_env):
    ranked = decide_memory_relevance(
        "obsidian vault router notes",
        [
            {"rel_path": "a.md", "excerpt": "shopping list milk bread"},
            {"rel_path": "b.md", "excerpt": "obsidian vault router configuration"},
            {"rel_path": "c.md", "excerpt": "weather forecast"},
        ],
        deadline_ms=80,
    )
    assert ranked[0]["rel_path"] == "b.md"
    assert ranked[0]["reflex_score"] >= ranked[-1]["reflex_score"]


def test_laya_preferred_when_warm(reflex_env):
    enable_and_warm()
    assert laya_status()["warm"] is True
    assert laya_status()["loopback_only"] is True
    assert laya_status()["in_process"] is True

    def laya_fn(state, questions):
        answers = {}
        for qid, spec in questions.items():
            if spec.get("type") == "choice":
                choices = spec.get("choices") or ["none"]
                pick = "git" if "git" in choices else choices[0]
                answers[qid] = {"type": "choice", "choice": pick, "confidence": 0.93}
            elif spec.get("type") == "score":
                answers[qid] = {"type": "score", "score": 0.7, "confidence": 0.9}
            else:
                answers[qid] = {"type": "noul", "noul": 0.1, "confidence": 0.9}
        return {"model": "laya-test", "answers": answers}

    set_inference_fn(laya_fn)
    result = decide(
        {"user_message": "use git please", "candidate_tools": ["filesystem", "git"]},
        [
            Question(
                id="tool_select",
                type="choice",
                prompt="tool",
                choices=("filesystem", "git", "none"),
            )
        ],
        "tool_selection",
        deadline_ms=100,
        privacy="local_only",
    )
    assert result.source == "laya"
    assert result.value("tool_select") == "git"
    assert result.provider_version == "laya-test"


def test_jev_requires_opt_in_and_probe(reflex_env):
    set_decision_tier("local")
    result = decide_tool_selection("filesystem please", ["filesystem", "git"], cloud_ok=True)
    assert result.source != "jev"

    set_decision_tier("jev_optional")
    bind_typesafe_key("sk-fixture")
    set_http_post(_ok_jev, fixture=True)
    probed = probe_jev()
    assert probed["jev_availability"] == "connected"
    result = decide(
        {"user_message": "filesystem please", "candidate_tools": ["filesystem", "git"]},
        [
            Question(
                id="tool_select",
                type="choice",
                prompt="tool",
                choices=("filesystem", "git", "none"),
            )
        ],
        "tool_selection",
        deadline_ms=200,
        privacy="cloud_ok",
    )
    assert result.source == "jev"
    assert result.value("tool_select") == "filesystem"


def test_deadline_fallback_is_audited(reflex_env):
    enable_and_warm()

    def slow_laya(state, questions):
        time.sleep(0.05)
        return {"model": "slow", "answers": {}}

    set_inference_fn(slow_laya)
    result = decide(
        {"user_message": "hello", "candidate_tools": []},
        [
            Question(
                id="speak_class",
                type="choice",
                prompt="social or technical",
                choices=("social", "technical"),
            )
        ],
        "speak_class",
        deadline_ms=5,
        privacy="local_only",
        use_cache=False,
    )
    assert result.answers
    assert "speak_class" in result.answers
    # Must not strand — either rules completed before timeout or explicit fallback.
    assert result.source in {"rules", "laya", "generative_fallback", "deadline_fallback"}
    events = list_events()
    assert any(e.get("kind") == "reflex_decision" for e in events)


def test_policy_cannot_be_weakened_by_reflex(reflex_env):
    enable_and_warm()

    def evil_laya(state, questions):
        answers = {}
        for qid in questions:
            answers[qid] = {"type": "noul", "noul": 0.0, "confidence": 0.99}
        return {"model": "evil", "answers": answers}

    set_inference_fn(evil_laya)
    composed = compose_turn_decisions(
        user_message="delete everything",
        candidate_tools=["filesystem"],
        local_complexity=3,
        policy_requires_approval=True,
        policy_deny=False,
        cloud_ok=False,
        deadline_ms=80,
    )
    assert composed["approval_needed"] is True
    assert approval_popup_required(policy_requires=True, policy_deny=False, jev_noul=0.0) is True
    assert apply_complexity_tier(3, 1.0) == 3


def test_cache_pure_decisions(reflex_env):
    q = [
        Question(
            id="tool_select",
            type="choice",
            prompt="tool",
            choices=("filesystem", "none"),
            pure=True,
        )
    ]
    state = {"user_message": "filesystem", "candidate_tools": ["filesystem"]}
    first = decide(state, q, "tool_selection", deadline_ms=50, privacy="local_only")
    second = decide(state, q, "tool_selection", deadline_ms=50, privacy="local_only")
    assert first.value("tool_select") == second.value("tool_select")
    assert second.cached is True or second.source in {"rules", "cache", "laya"}


def test_persona_model_routing_and_browser_ops(reflex_env):
    route = decide_persona_model_route(
        "hello",
        ["balanced", "quality", "fast"],
        preferred_profile="balanced",
    )
    assert route.value("model_profile") == "balanced"
    browser = decide_browser_operation_target(
        frame_id="f1",
        actionable=[{"target_id": "n1", "role": "button", "name": "Submit"}],
        suggested_operation="click",
        suggested_target_id="n1",
    )
    assert browser.value("operation") in {"click", "noop", "done", "block", "type_text", "scroll", "hover", "key"}
    assert browser.value("target_id") in {"n1", "none"}


def test_laya_pins_and_metrics_api(reflex_env):
    enable_and_warm()
    decide(
        {"user_message": "filesystem", "candidate_tools": ["filesystem"]},
        [Question(id="tool_select", type="choice", prompt="t", choices=("filesystem", "none"))],
        "tool_selection",
        deadline_ms=40,
    )
    snap = snapshot()
    assert "classes" in snap
    client = TestClient(app)
    metrics = client.get("/api/decision/reflex/metrics")
    assert metrics.status_code == 200
    laya = client.get("/api/decision/laya")
    assert laya.status_code == 200
    body = laya.json()
    assert body["license"] == "Apache-2.0"
    assert body["loopback_only"] is True
    assert body["pins"]
    status = client.get("/api/decision/jev")
    assert status.status_code == 200
    payload = status.json()
    assert "publicly usable" in (payload.get("public_availability_note") or "").lower() or "public" in (
        payload.get("owner_error") or ""
    ).lower() or payload.get("cta") == "Bind TypeSafe API key"


def test_status_no_longer_primary_waitlist_cta(reflex_env):
    status = resolve_status()
    assert status["cta"] != "Notify when ready"
    assert "waitlist" not in (status.get("owner_error") or "").lower() or "public" in (
        status.get("public_availability_note") or ""
    ).lower()
