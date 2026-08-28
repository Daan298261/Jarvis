from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.policy.audit import list_audit_events, reset_audit_log
from app.policy.authorize import authorize
from app.policy.inheritance import resolve_effective_level
from app.policy.levels import AutonomyLevel
from app.policy.store import (
    create_profile,
    get_platform_policy,
    reset_policy_store,
    update_platform_policy,
    update_profile,
)
from app.tools.base import RiskLevel


@pytest.fixture
def policy_store(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    reset_policy_store()
    reset_audit_log()
    yield jarvis_env["tmp"]


def _create_research_profile(policy_store):
    return create_profile(
        name="Research Analyst",
        interview_answers={
            "mission": "Research competitors and summarize findings",
            "success_criteria": "Actionable weekly brief",
            "tone": "concise",
            "allowed_channels": ["web_fetch", "filesystem"],
            "approval_required_actions": ["git push", "send"],
            "default_autonomy": "L3_EXECUTE_WITH_GATES",
            "hard_prohibitions": ["no terminal shell access"],
        },
        actor="tester",
    )


def test_profile_stores_interview_policy_and_prompt_separately(policy_store):
    profile = _create_research_profile(policy_store)
    assert profile["interview_answers"]["mission"].startswith("Research")
    assert isinstance(profile["policy"], dict)
    assert profile["policy"].get("autonomy")
    assert profile["generated_prompt"]
    assert "Mission:" in profile["generated_prompt"]
    assert profile["policy"] is not profile["interview_answers"]


def test_autonomy_inheritance_and_platform_cap(policy_store):
    profile = create_profile(
        name="Ops",
        interview_answers={"default_autonomy": "L4_AUTONOMOUS"},
        policy={
            "autonomy": {
                "*": "L4_AUTONOMOUS",
                "terminal": "L4_AUTONOMOUS",
                "terminal.exec": "L4_AUTONOMOUS",
            }
        },
        actor="tester",
    )
    update_platform_policy(
        autonomy_caps={"*": "L3_EXECUTE_WITH_GATES", "terminal": "L2_EXECUTE_SAFE"},
        actor="admin",
    )
    effective = resolve_effective_level(
        "terminal.exec",
        profile["policy"]["autonomy"],
        get_platform_policy()["autonomy_caps"],
    )
    assert effective == AutonomyLevel.L2_EXECUTE_SAFE

    child_effective = resolve_effective_level(
        "terminal.exec",
        {"terminal.exec": "L4_AUTONOMOUS", "terminal": "L3_EXECUTE_WITH_GATES", "*": "L2_EXECUTE_SAFE"},
        {"*": "L5_OPERATOR"},
    )
    assert child_effective == AutonomyLevel.L4_AUTONOMOUS


def test_authorize_denies_observe_and_suggest(policy_store):
    denied = authorize(
        "filesystem",
        action="read",
        risk=RiskLevel.LOW,
        agent_autonomy={"*": AutonomyLevel.L1_SUGGEST.value},
        platform_caps={"*": AutonomyLevel.L5_OPERATOR.value},
    )
    assert denied.allowed is False
    assert denied.requires_approval is False


def test_authorize_requires_approval_for_gated_high_risk(policy_store):
    profile = create_profile(
        name="Gated",
        interview_answers={
            "default_autonomy": "L3_EXECUTE_WITH_GATES",
            "approval_required_actions": ["terminal"],
        },
        actor="tester",
    )
    pending = authorize(
        "terminal",
        risk=RiskLevel.HIGH,
        profile_id=profile["id"],
    )
    assert pending.allowed is False
    assert pending.requires_approval is True

    approved = authorize(
        "terminal",
        risk=RiskLevel.HIGH,
        profile_id=profile["id"],
        approved=True,
    )
    assert approved.allowed is True


def test_platform_cap_denies_even_with_high_agent_autonomy(policy_store):
    profile = create_profile(
        name="Power",
        interview_answers={"default_autonomy": "L5_OPERATOR"},
        policy={"autonomy": {"*": "L5_OPERATOR", "terminal": "L5_OPERATOR"}},
        actor="tester",
    )
    update_platform_policy(autonomy_caps={"*": "L3_EXECUTE_WITH_GATES", "terminal": "L1_SUGGEST"}, actor="admin")
    result = authorize("terminal", risk=RiskLevel.LOW, profile_id=profile["id"])
    assert result.allowed is False
    assert result.effective_level == AutonomyLevel.L1_SUGGEST


def test_policy_edits_are_audited(policy_store):
    profile = _create_research_profile(policy_store)
    update_profile(
        profile["id"],
        policy={
            **profile["policy"],
            "autonomy": {**profile["policy"]["autonomy"], "browser": "L2_EXECUTE_SAFE"},
        },
        actor="editor",
    )
    events = list_audit_events(profile_id=profile["id"])
    fields = {event["field"] for event in events}
    assert "profile.created" in fields
    assert "policy" in fields
    platform_events = list_audit_events(profile_id=None)
    assert any(event["field"].startswith("platform.") for event in platform_events) or "policy" in fields


def test_agent_policy_api_roundtrip(policy_store):
    client = TestClient(app)
    created = client.post(
        "/api/agent-policy",
        json={
            "name": "API Agent",
            "interview_answers": {
                "mission": "Support API testing",
                "default_autonomy": "L3_EXECUTE_WITH_GATES",
            },
            "actor": "api-user",
        },
    )
    assert created.status_code == 200
    profile_id = created.json()["id"]

    fetched = client.get(f"/api/agent-policy/{profile_id}")
    assert fetched.status_code == 200
    assert fetched.json()["interview_answers"]["mission"] == "Support API testing"

    authz = client.post(
        "/api/agent-policy/authorize",
        json={"tool_name": "web_fetch", "risk": "medium", "profile_id": profile_id},
    )
    assert authz.status_code == 200
    assert authz.json()["allowed"] is True

    platform = client.put(
        "/api/agent-policy/platform",
        json={"autonomy_caps": {"*": "L2_EXECUTE_SAFE"}, "actor": "admin"},
    )
    assert platform.status_code == 200

    denied = client.post(
        "/api/agent-policy/authorize",
        json={"tool_name": "web_fetch", "risk": "medium", "profile_id": profile_id},
    )
    assert denied.status_code == 200
    assert denied.json()["allowed"] is False
