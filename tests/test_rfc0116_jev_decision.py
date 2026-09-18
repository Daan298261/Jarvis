from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.decision.audit import list_events, reset_audit
from app.decision.jev_client import reset_http_post, set_http_post
from app.decision.policy import apply_complexity_tier, approval_popup_required, local_complexity_tier, rerank_tools
from app.decision.tier import (
    bind_typesafe_key,
    decide_turn,
    jev_calls_allowed,
    plus_entitled,
    probe_jev,
    resolve_status,
    set_decision_tier,
    set_notify_requested,
)
from app.licensing.entitlements import FEATURE_JEV_PLUS, evaluate_cluster_entitlements, has_feature
from app.licensing.store import reset_licensing_store
from app.main import app
from app.tts.reply_class import classify_reply_for_speech, register_reply_classifier_hook


def _ok_probe(_url, _headers, body, _timeout):
    questions = body.get("questions") or {}
    answers = {}
    if "ready" in questions:
        answers["ready"] = {"type": "noul", "noul": 0.91, "confidence": 0.94}
    if "speak_class" in questions:
        answers["speak_class"] = {"type": "choice", "choice": "social", "confidence": 0.88}
    if "complexity_tier" in questions:
        answers["complexity_tier"] = {"type": "score", "score": 1.0, "confidence": 0.8}
    if "escalate" in questions:
        answers["escalate"] = {"type": "noul", "noul": 0.04, "confidence": 0.9}
    if "approval_needed" in questions:
        answers["approval_needed"] = {"type": "noul", "noul": 0.1, "confidence": 0.9}
    if "tool_select" in questions:
        choices = questions["tool_select"].get("choices") or ["none"]
        pick = "filesystem" if "filesystem" in choices else choices[0]
        answers["tool_select"] = {"type": "choice", "choice": pick, "confidence": 0.7}
    return 200, {"model": "jev-latest", "answers": answers}, ""


def _fail_401(_url, _headers, _body, _timeout):
    return 401, {"error": "unauthorized"}, "unauthorized"


@pytest.fixture
def jev_env(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    settings: AppSettings = jarvis_env["settings"]
    monkeypatch.setattr("app.config.data_dir", lambda: tmp)
    monkeypatch.setattr("app.licensing.cluster.data_dir", lambda: tmp)
    reset_licensing_store()
    reset_audit()
    reset_http_post()
    register_reply_classifier_hook(None)
    settings.decision.tier = "local"
    settings.decision.notify_requested_at = ""
    settings.decision.plus_features = []
    settings.decision.last_availability = "unavailable"
    settings.decision.last_probe_error = ""
    settings.decision.last_model = ""
    yield {"tmp": tmp, "settings": settings}
    reset_http_post()
    register_reply_classifier_hook(None)
    reset_audit()


def test_local_default_never_opens_typesafe(jev_env):
    calls: list[str] = []

    def spy(url, headers, body, timeout):
        calls.append(url)
        raise AssertionError("local tier must not open TypeSafe")

    set_http_post(spy, fixture=True)
    set_decision_tier("local")
    status = resolve_status()
    assert status["decision_tier"] == "local"
    assert status["jev_availability"] != "connected"
    allowed, reason = jev_calls_allowed(status)
    assert allowed is False
    assert "local" in reason
    decision = decide_turn(user_message="hello", candidate_tools=["filesystem", "git", "browser"])
    assert decision["source"] != "jev"
    assert decision["fallback_used"] is True
    assert calls == []
    assert probe_jev()["probed"] is False


def test_waitlist_notify_is_not_connected(jev_env):
    stamp = set_notify_requested()
    status = resolve_status()
    assert stamp
    assert status["notify_requested_at"]
    assert status["jev_availability"] in {"waitlisted", "unavailable"}
    assert status["jev_availability"] != "connected"
    assert "connected" not in (status["cta"] or "").lower()


def test_plus_entitlement_goes_through_has_feature(jev_env):
    settings: AppSettings = jev_env["settings"]
    assert has_feature(None, FEATURE_JEV_PLUS) is False
    assert plus_entitled() is False
    settings.decision.plus_features = [FEATURE_JEV_PLUS]
    entitlements = evaluate_cluster_entitlements(None)
    assert FEATURE_JEV_PLUS in entitlements["features"]
    assert has_feature(None, FEATURE_JEV_PLUS) is True
    set_decision_tier("jev_plus")
    bind_typesafe_key("sk-test-not-live")
    set_http_post(_ok_probe, fixture=True)
    probed = probe_jev()
    assert probed["plus_entitled"] is True
    settings.decision.plus_features = []
    set_decision_tier("jev_plus")
    blocked = probe_jev()
    assert has_feature(None, FEATURE_JEV_PLUS) is False
    assert blocked["plus_entitled"] is False
    assert blocked["probed"] is False
    assert "Plus entitlement" in (blocked["owner_error"] or blocked.get("cta") or "")


def test_probe_failure_is_error_not_connected(jev_env):
    set_decision_tier("jev_optional")
    bind_typesafe_key("sk-bad")
    set_http_post(_fail_401, fixture=True)
    result = probe_jev()
    assert result["jev_availability"] == "error"
    assert result["ok"] is False
    events = list_events()
    assert events
    assert events[0]["kind"] == "jev_error"
    assert events[0]["source"] != "jev"


def test_labeled_fixture_probe_can_connect(jev_env):
    set_decision_tier("jev_optional")
    bind_typesafe_key("sk-fixture")
    set_http_post(_ok_probe, fixture=True)
    result = probe_jev()
    assert result["ok"] is True
    assert result["jev_availability"] == "connected"
    assert result["fixture"] is True
    decision = decide_turn(
        user_message="list my documents",
        candidate_tools=["filesystem", "git"],
        local_complexity=2,
        policy_requires_approval=True,
    )
    assert decision["source"] == "jev"
    assert decision["fallback_used"] is False
    assert decision["tool_select"] == "filesystem"
    assert len(decision.get("answers") or {}) <= 6
    assert decision["approval_needed"] is True


def test_jev_does_not_rank_full_catalog(jev_env):
    set_decision_tier("jev_optional")
    bind_typesafe_key("sk-fixture")
    set_http_post(_ok_probe, fixture=True)
    probe_jev()
    ranked = rerank_tools("please use the filesystem", ["filesystem", "git"])
    assert set(ranked) <= {"filesystem", "git"}
    assert "hexstrike_operator" not in ranked


def test_complexity_jev_cannot_lower_hard_tier():
    assert local_complexity_tier("hello") == 1
    assert apply_complexity_tier(3, 1.0) == 3
    assert apply_complexity_tier(2, 4.2) == 4


def test_approval_noul_cannot_skip_required_or_weaken_deny():
    assert approval_popup_required(policy_requires=True, policy_deny=False, jev_noul=0.0) is True
    assert approval_popup_required(policy_requires=False, policy_deny=True, jev_noul=0.99) is False
    assert approval_popup_required(policy_requires=False, policy_deny=False, jev_noul=0.8) is True


def test_speak_class_defers_to_hard_technical(jev_env):
    register_reply_classifier_hook(lambda *_args: "social")
    body = "Traceback (most recent call last):\n  File \"loop.py\", line 4\nRuntimeError: boom"
    assert classify_reply_for_speech(body) == "technical"


def test_jev_status_api_defaults_local(jev_env):
    client = TestClient(app)
    status = client.get("/api/decision/jev")
    assert status.status_code == 200
    payload = status.json()
    assert payload["decision_tier"] == "local"
    assert payload["jev_availability"] != "connected"
    notify = client.post("/api/decision/jev/notify")
    assert notify.status_code == 200
    assert notify.json()["jev_availability"] != "connected"
    audit = client.get("/api/decision/jev/audit")
    assert audit.status_code == 200
    assert "events" in audit.json()
