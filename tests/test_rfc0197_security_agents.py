"""RFC-0197 blue / red / purple security agents — backend unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.cyber_execution import (
    applies_cyber_tool_execution,
    cyber_completion_blocked_message,
    cyber_execution_satisfied,
    init_cyber_execution,
    note_cyber_tool,
)
from app.agent.planning import WorkingState
from app.agent.tool_exposure import tool_names_for
from app.main import app
from app.policy.cyber_ato import AtoStatus
from app.security.security_agents import (
    SecurityAgentDenied,
    advance_purple_phase,
    assert_mode_entitled,
    init_purple,
    list_handoffs,
    load_purple_state,
    mode_tools,
    persona_bind_for_mode,
    stop_purple,
)
from app.security.security_audit import audit_path, read_audit_lines
from app.security.target_registry import (
    TargetDenied,
    add_target,
    assert_targets_allowed,
    list_targets,
    remove_target,
)


def _ato(**overrides: object) -> AtoStatus:
    values = dict(
        installed=True,
        valid=True,
        law_enforcement=False,
        blue_team=True,
        red_team=False,
        in_person_verified=True,
        expired=False,
        renewal_due=False,
        can_issue=False,
        package_class="",
        modules=["blue-team"],
        reason="",
        clock_rollback=False,
    )
    values.update(overrides)
    return AtoStatus(**values)  # type: ignore[arg-type]


@pytest.fixture
def security_store(jarvis_env, monkeypatch):
    tmp: Path = jarvis_env["tmp"]
    monkeypatch.setattr("app.security.target_registry.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.security_audit.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.security_agents.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike_operator.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike_defensive.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike_defensive.load_settings", lambda: jarvis_env["settings"])
    return tmp


def test_persona_binds_themis_veles():
    blue = persona_bind_for_mode("blue")
    red = persona_bind_for_mode("red")
    purple = persona_bind_for_mode("purple")
    assert blue["primary_persona_id"] == "themis"
    assert red["primary_persona_id"] == "veles"
    assert set(purple["persona_ids"]) == {"themis", "veles"}


def test_deny_red_without_law_enforcement(monkeypatch, security_store):
    status = _ato(modules=["red-team"], law_enforcement=False, red_team=True, blue_team=False)
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    with pytest.raises(SecurityAgentDenied, match="law_enforcement"):
        assert_mode_entitled("red")
    events = read_audit_lines()
    assert any(row.get("reason") == "red_requires_law_enforcement" for row in events)


def test_allow_red_with_module_and_le(monkeypatch, security_store):
    status = _ato(
        modules=["blue-team", "red-team", "hexstrike"],
        law_enforcement=True,
        red_team=True,
        blue_team=True,
    )
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    assert assert_mode_entitled("red") == "red-team"
    assert assert_mode_entitled("purple") == "purple-team"


def test_deny_unlisted_target_and_audit(security_store):
    with pytest.raises(TargetDenied, match="not in the owner-attested"):
        assert_targets_allowed({"target": "203.0.113.50"}, security_role="blue-team", capability_id="http:scan")
    events = read_audit_lines()
    assert any(
        row.get("event") == "invoke_denied" and row.get("reason") == "target_not_registered" for row in events
    )


def test_registered_target_allows_operate_args(security_store):
    row = add_target(kind="ipv4", value="10.0.0.8", notes="lab")
    assert row["id"]
    assert_targets_allowed({"target": "10.0.0.8"}, security_role="blue-team")
    removed = remove_target(row["id"])
    assert removed["value"] == "10.0.0.8"
    events = read_audit_lines()
    assert any(row.get("event") == "target_added" for row in events)
    assert any(row.get("event") == "target_removed" for row in events)


@pytest.mark.asyncio
async def test_operate_denies_unlisted_target(security_store, monkeypatch):
    from app.security.hexstrike_operator import operate

    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    with pytest.raises(TargetDenied):
        await operate("http:scanner_one", {"target": "198.51.100.20"})


def test_tool_exposure_maps_per_mode(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.agent.tool_exposure.hexstrike_access_mode", lambda now=None: "full")
    from app.tools.registry import REGISTRY

    REGISTRY.apply_settings(jarvis_env["settings"])
    names_blue = set(tool_names_for("mixed", security_role="blue-team", prompt="run defensive inventory"))
    names_red = set(tool_names_for("mixed", security_role="red-team", prompt="scoped red assessment"))
    names_purple = set(tool_names_for("mixed", security_role="purple-team", prompt="purple loop"))
    assert "hexstrike_operator" in names_blue
    assert "hexstrike_defensive" in names_blue
    assert "hexstrike_operator" in names_red
    assert "hexstrike_defensive" not in set(mode_tools("red-team"))
    assert "hexstrike_operator" in names_purple
    assert "hexstrike_defensive" in names_purple


def test_cyber_verify_rejects_narration_only():
    working = WorkingState(security_role="blue-team")
    init_cyber_execution(working, requires_tool_execution=True)
    assert applies_cyber_tool_execution("blue-team", "run defensive inventory")
    assert cyber_execution_satisfied(working) is False
    assert "requires_tool_execution" in cyber_completion_blocked_message(working)
    note_cyber_tool(
        working,
        "hexstrike_operator",
        {"operation": "operate", "capability_id": "defensive:lan_inventory"},
        json.dumps({"status": "succeeded", "id": "job-1"}),
        success=True,
    )
    assert cyber_execution_satisfied(working) is True


def test_purple_phase_transitions_and_handoffs(security_store):
    task_id = "purple-task-1"
    state = init_purple(task_id)
    assert state.phase == "blue"
    assert state.locked is False
    result = advance_purple_phase(
        task_id,
        findings=[{"title": "baseline ok"}],
        evidence_paths=["/tmp/evidence.json"],
        open_questions=["confirm lab CIDR"],
    )
    assert result["state"]["phase"] == "red"
    assert result["handoff"]["from_phase"] == "blue"
    assert result["handoff"]["to_phase"] == "red"
    assert list_handoffs(task_id)
    # Cannot run both phases' tools conceptually — active phase is red now
    assert "hexstrike_defensive" not in mode_tools("purple-team", purple_phase="red")
    assert "hexstrike_operator" in mode_tools("purple-team", purple_phase="red")
    stopped = stop_purple(task_id)
    assert stopped["state"]["locked"] is True
    with pytest.raises(SecurityAgentDenied, match="locked"):
        advance_purple_phase(task_id)


def test_api_mode_deny_red_without_le(jarvis_env, security_store, monkeypatch, allow_loopback_api):
    status = _ato(modules=["red-team"], law_enforcement=False, red_team=True)
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    client = TestClient(app)
    response = client.post("/api/security-agents/mode", json={"mode": "red", "prompt": "assess lab"})
    assert response.status_code == 403
    assert "law_enforcement" in response.json()["detail"]


def test_api_target_crud_and_mode_blue(jarvis_env, security_store, monkeypatch, allow_loopback_api):
    status = _ato(modules=["blue-team", "hexstrike"], law_enforcement=False, blue_team=True)
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    client = TestClient(app)
    created = client.post(
        "/api/security-agents/targets",
        json={"kind": "ipv4", "value": "10.0.0.20", "notes": "lab box"},
    )
    assert created.status_code == 200
    target_id = created.json()["id"]
    listed = client.get("/api/security-agents/targets")
    assert listed.status_code == 200
    assert any(row["id"] == target_id for row in listed.json()["targets"])
    mode = client.post("/api/security-agents/mode", json={"mode": "blue", "prompt": "inventory my lab"})
    assert mode.status_code == 200
    body = mode.json()
    assert body["security_role"] == "blue-team"
    assert body["persona_bind"]["primary_persona_id"] == "themis"
    assert body["task"]["security_role"] == "blue-team"
    deleted = client.delete(f"/api/security-agents/targets/{target_id}")
    assert deleted.status_code == 200
    assert audit_path().is_file()


def test_api_purple_advance(jarvis_env, security_store, monkeypatch, allow_loopback_api):
    status = _ato(
        modules=["blue-team", "red-team", "hexstrike"],
        law_enforcement=True,
        blue_team=True,
        red_team=True,
    )
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    client = TestClient(app)
    mode = client.post(
        "/api/security-agents/mode",
        json={"mode": "purple", "prompt": "coordinate blue then red on attested lab"},
    )
    assert mode.status_code == 200
    task_id = mode.json()["task"]["id"]
    assert mode.json()["purple"]["phase"] == "blue"
    advanced = client.post(
        f"/api/security-agents/tasks/{task_id}/purple/advance",
        json={"findings": ["observe done"], "evidence_paths": [], "open_questions": []},
    )
    assert advanced.status_code == 200
    assert advanced.json()["state"]["phase"] == "red"
    state = client.get(f"/api/security-agents/tasks/{task_id}/purple")
    assert state.status_code == 200
    assert state.json()["state"]["phase"] == "red"
    stop = client.post(f"/api/security-agents/tasks/{task_id}/purple/stop")
    assert stop.status_code == 200
    assert stop.json()["state"]["locked"] is True


def test_create_task_persists_purple_team(jarvis_env, security_store, monkeypatch, allow_loopback_api):
    status = _ato(
        modules=["blue-team", "red-team"],
        law_enforcement=True,
        blue_team=True,
        red_team=True,
    )
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    client = TestClient(app)
    response = client.post(
        "/api/tasks",
        json={"prompt": "purple security agent on my lab", "security_role": "purple-team"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["security_role"] == "purple-team"
    assert payload["requires_tool_execution"] is True
    assert load_purple_state(payload["id"]).phase == "blue"


def test_list_targets_empty_by_default(security_store):
    assert list_targets() == []
