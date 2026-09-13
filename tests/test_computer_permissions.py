from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.policy.authorize import authorize
from app.policy.computer_permissions import (
    apply_grant,
    blue_isolate_playbook,
    confirmation_payload_for_tool,
    consume_once_grants,
    evaluate_permission,
    evaluate_tool_permissions,
    permission_ids_for_tool,
    reset_computer_permission_state,
)
from app.tools.base import RiskLevel
from app.workers.remote_desktop import rdp_command, validate_rdp_host


@pytest.fixture
def permission_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.inference.security_gates.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    return tmp_path


def test_desktop_defaults_to_ask(permission_store):
    ids = permission_ids_for_tool("desktop", {"action": "click"})
    assert ids == ["computer.this_device"]
    decision = evaluate_tool_permissions("desktop", {"action": "click"})
    assert decision.status == "ask"
    authz = authorize("desktop", action="click", arguments={"action": "click"}, risk=RiskLevel.MEDIUM)
    assert authz.allowed is False
    assert authz.requires_approval is True


def test_worker_rdp_maps_both_permissions(permission_store):
    ids = permission_ids_for_tool("desktop", {"node_id": "abc", "rdp_host": "192.168.1.20"})
    assert ids == ["computer.worker_nodes", "computer.rdp"]


def test_web_fetch_splits_internet_and_local(permission_store):
    assert permission_ids_for_tool("web_fetch", {"url": "https://example.com"}) == ["network.internet"]
    assert permission_ids_for_tool("web_fetch", {"url": "http://192.168.1.1/status"}) == ["network.local"]
    assert permission_ids_for_tool("browser", {"url": "http://nas.local"}) == ["network.local"]


def test_allow_once_is_consumed_after_use(permission_store):
    apply_grant("computer.this_device", "allow_once", persist=False)
    assert evaluate_permission("computer.this_device").status == "allow"
    consume_once_grants(["computer.this_device"])
    assert evaluate_permission("computer.this_device").status == "ask"


def test_always_allow_desktop(permission_store):
    apply_grant("computer.this_device", "always")
    authz = authorize("desktop", arguments={"action": "focus"}, risk=RiskLevel.MEDIUM)
    assert authz.allowed is True
    assert authz.requires_approval is False


def test_red_flags_stay_denied_without_gate(permission_store):
    decision = evaluate_permission("red.entry")
    assert decision.status == "deny"
    assert "gate" in decision.reason.lower() or "locked" in decision.reason.lower()
    with pytest.raises(PermissionError):
        apply_grant("red.entry", "always")


def test_blue_isolate_is_a_playbook_not_an_executor(permission_store):
    with pytest.raises(PermissionError):
        apply_grant("blue.isolate_device", "always")
    plan = blue_isolate_playbook(device="printer.lan", reason="lab containment")
    assert plan["executed"] is False
    assert plan["status"] == "deny"
    assert any("Do not deauth" in step or "kick" in step.lower() for step in plan["steps"])


def test_confirmation_payload_is_chatgpt_shaped(permission_store):
    payload = confirmation_payload_for_tool(
        call_id="call-1",
        name="desktop",
        arguments={"action": "click"},
        irreversible=False,
    )
    assert payload["kind"] == "permission"
    assert payload["permission_id"] == "computer.this_device"
    assert "allow_once" in payload["options"]
    assert payload["title"]
    assert "search the internet" in payload["spoken_prompt"].lower() or "this computer" in payload["spoken_prompt"].lower()
    assert payload["voice_reply_hint"]


def test_web_fetch_spoken_prompt_asks_to_grant_internet(permission_store):
    payload = confirmation_payload_for_tool(
        call_id="call-web",
        name="web_fetch",
        arguments={"url": "https://example.com"},
    )
    assert payload["permission_id"] == "network.internet"
    assert "search the internet" in payload["spoken_prompt"].lower()
    assert "sir" in payload["spoken_prompt"].lower()


def test_interpret_spoken_grant_maps_yes_always_no():
    from app.policy.computer_permissions import interpret_spoken_grant

    assert interpret_spoken_grant("Yes sir") == "allow_once"
    assert interpret_spoken_grant("I grant it") == "allow_once"
    assert interpret_spoken_grant("Always allow") == "always"
    assert interpret_spoken_grant("No") == "deny"
    assert interpret_spoken_grant("Don't allow") == "deny"
    assert interpret_spoken_grant("Do you grant it?") is None
    assert interpret_spoken_grant("") is None


def test_sapi_prefers_british_male_for_kokoro_butler_ids():
    from app.tts.system_sapi import _sapi_voice_select_script

    script = _sapi_voice_select_script("bm_daniel")
    assert "en-GB" in script
    assert "Male" in script
    named = _sapi_voice_select_script("Microsoft Hazel Desktop")
    assert "SelectVoice" in named
    assert "Microsoft Hazel Desktop" in named


def test_rdp_host_validation():
    assert validate_rdp_host("office-pc.local") == "office-pc.local"
    with pytest.raises(ValueError):
        validate_rdp_host("office pc & calc")
    command = rdp_command("192.168.1.50")
    assert command[0] in {"mstsc", "xfreerdp"}
    assert any("192.168.1.50" in part for part in command)


def test_permissions_api_lists_catalog(jarvis_env, permission_store):
    client = TestClient(app)
    response = client.get("/api/permissions")
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["permissions"]}
    assert "computer.this_device" in ids
    assert "network.internet" in ids
    assert "network.local" in ids
    assert "cyber.hexstrike" in ids
    assert "blue.isolate_device" in ids
    assert "red.entry" in ids
    denied = client.put("/api/permissions/red.exploration", json={"mode": "always"})
    assert denied.status_code == 403


def test_computer_use_plan_endpoint(jarvis_env, permission_store, monkeypatch):
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: permission_store)

    async def _targets():
        return [
            {
                "node_id": "local-1",
                "hostname": "leader",
                "address": "127.0.0.1",
                "is_local": True,
                "kind": "this_device",
                "desktop_control": True,
                "status": "online",
                "rdp_host": None,
            },
            {
                "node_id": "worker-1",
                "hostname": "office-pc",
                "address": "192.168.1.40",
                "is_local": False,
                "kind": "worker_node",
                "desktop_control": True,
                "status": "online",
                "rdp_host": "192.168.1.40",
            },
        ]

    monkeypatch.setattr("app.workers.computer_use_plan.list_computer_targets", _targets)
    monkeypatch.setattr("app.workers.computer_use_plan._local_backends", lambda: {"native_desktop": {"id": "desktop"}})
    client = TestClient(app)
    response = client.post(
        "/api/computer-use/plan",
        json={
            "goal": "Open Notepad on the office PC",
            "source": "phone",
            "preferred_node_id": "worker-1",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "phone"
    assert body["target"]["node_id"] == "worker-1"
    assert body["rdp"]["host"] == "192.168.1.40"
    assert any("192.168.1.40" in part for part in body["rdp"]["command"])
    isolate = client.post("/api/computer-use/blue/isolate", json={"device": "cam-1", "reason": "owned LAN"})
    assert isolate.status_code == 403
