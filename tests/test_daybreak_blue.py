from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.api.tasks import _task_dict
from app.db.models import Task
from app.db.session import SessionLocal
from app.main import app
from app.policy.computer_permissions import permission_ids_for_tool
from app.security.hexstrike import HEXSTRIKE
from app.security.hexstrike_defensive import (
    capability_snapshot,
    execute_defensive,
    list_jobs,
    normalize_scope,
    stop_managed_job,
    upsert_scope,
)
from app.security.hexstrike_install import (
    APPROVED_HEXSTRIKE_COMMIT,
    APPROVED_HEXSTRIKE_REMOTE,
    HexStrikeInstaller,
)
from app.tools.hexstrike_defensive import HexStrikeDefensiveTool
from app.agent.planning import follow_up_stays_conversation, is_defensive_operator_prompt


@pytest.fixture
def blue_store(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.security.hexstrike_defensive.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike_defensive.load_settings", lambda: jarvis_env["settings"])
    return tmp


def test_scope_validation_accepts_owner_local_assets_and_rejects_public(blue_store):
    local = upsert_scope(
        "host",
        kind="local_infrastructure",
        value="local",
        label="This host",
        attested_owned=True,
    )
    assert local["attested_owned"] is True
    assert normalize_scope("private_cidr", "192.168.20.0/24") == "192.168.20.0/24"
    assert normalize_scope("container_image", "alpine:3.20") == "alpine:3.20"
    with pytest.raises(PermissionError):
        upsert_scope("no-attestation", kind="private_host", value="10.0.0.4", label="", attested_owned=False)
    with pytest.raises(ValueError, match="public"):
        normalize_scope("private_host", "8.8.8.8")
    with pytest.raises(ValueError):
        normalize_scope("private_host", "example.com")
    unsafe_path = blue_store / "evidence & whoami"
    with pytest.raises(ValueError, match="safely supported"):
        normalize_scope("local_path", str(unsafe_path))


def test_only_typed_defensive_capabilities_are_published():
    ids = {item["id"] for item in capability_snapshot()}
    assert ids == {
        "lan_inventory",
        "container_scan",
        "iac_scan",
        "host_baseline",
        "forensic_inspection",
        "threat_intel_lookup",
    }
    assert not ids.intersection({"command", "payload", "exploit", "credential_attack"})


@pytest.mark.asyncio
async def test_execution_and_stop_are_managed_and_audited(blue_store, monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "app.security.hexstrike_defensive.audit_hexstrike",
        lambda action, **fields: events.append((action, fields)),
    )
    upsert_scope("host", kind="local_infrastructure", value="local", label="Host", attested_owned=True)

    async def fake_post(path, payload):
        assert path == "api/tools/docker-bench-security"
        assert payload == {"output_file": ""}
        return {"pid": 4321, "status": "started"}

    monkeypatch.setattr(HEXSTRIKE, "post_defensive", fake_post)
    job = await execute_defensive("host_baseline", "host")
    assert job["status"] == "completed"
    assert job["upstream_pid"] == 4321
    assert any(action == "defensive_action_started" for action, _ in events)

    async def fake_stop(path, payload):
        assert path == "api/processes/terminate/4321"
        return {"stopped": True}

    monkeypatch.setattr(HEXSTRIKE, "post_defensive", fake_stop)
    stopped = await stop_managed_job(job["id"])
    assert stopped["status"] == "stopped"
    with pytest.raises(KeyError):
        await stop_managed_job("not-a-managed-job")
    assert any(action == "managed_stop_denied" for action, _ in events)


@pytest.mark.asyncio
async def test_operator_proxy_blocks_command_routes_but_allows_discovered_tools(monkeypatch):
    monkeypatch.setattr(HEXSTRIKE, "_base_status", lambda: SimpleNamespace(running=True, host="127.0.0.1", port=8888))
    for path in ("api/command", "api/payload/generate", "api/exploits/run"):
        with pytest.raises(PermissionError):
            await HEXSTRIKE.post_operator(path, {})
    async def fake_post(url_path, payload):
        return {"ok": True, "path": url_path}

    monkeypatch.setattr(HEXSTRIKE, "post_operator", fake_post)
    assert await HEXSTRIKE.post_operator("api/tools/custom-scanner", {}) == {
        "ok": True,
        "path": "api/tools/custom-scanner",
    }


def test_role_limited_tool_exposure(monkeypatch):
    from app.agent import tool_exposure
    from app.licensing.entitlements import HEXSTRIKE_ACCESS_BLUE, HEXSTRIKE_ACCESS_FULL, HEXSTRIKE_ACCESS_LOCKED

    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda: HEXSTRIKE_ACCESS_LOCKED)
    assert "hexstrike_defensive" not in tool_exposure.tool_names_for("mixed")
    assert "hexstrike_defensive" not in tool_exposure.tool_names_for("mixed", ["hexstrike_defensive"])
    assert "hexstrike_operator" not in tool_exposure.tool_names_for("mixed", ["hexstrike"])

    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda: HEXSTRIKE_ACCESS_BLUE)
    assert "hexstrike_defensive" in tool_exposure.tool_names_for("mixed", ["hexstrike_defensive"])
    assert "hexstrike_defensive" in tool_exposure.tool_names_for("mixed", security_role="blue-team")
    assert "hexstrike_operator" not in tool_exposure.tool_names_for("mixed", ["hexstrike"])

    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda: HEXSTRIKE_ACCESS_FULL)
    assert "hexstrike_operator" in tool_exposure.tool_names_for("mixed", ["hexstrike"])


@pytest.mark.asyncio
async def test_defensive_tool_rechecks_role_gate_and_permissions(monkeypatch):
    context = {"security_role": ""}
    tool = HexStrikeDefensiveTool(lambda: context)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "locked")
    denied = await tool.execute(action="host_baseline", scope_id="host")
    assert denied.success is False
    assert "Pro feature" in (denied.error or "")

    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "blue")
    monkeypatch.setattr(
        "app.tools.hexstrike_defensive.evaluate_permission",
        lambda permission: SimpleNamespace(status="allow"),
    )

    async def fake_execute(action, scope_id, options):
        return {"id": "job", "action": action, "scope_id": scope_id, "status": "completed"}

    monkeypatch.setattr("app.tools.hexstrike_defensive.execute_defensive", fake_execute)
    allowed = await tool.execute(action="host_baseline", scope_id="host")
    assert allowed.success is True


def test_defensive_permission_mapping_requires_cyber_and_blue():
    assert permission_ids_for_tool("hexstrike_defensive", {"action": "host_baseline"}) == [
        "cyber.hexstrike",
        "blue.static_rules",
    ]
    assert permission_ids_for_tool("hexstrike_defensive", {"action": "lan_inventory"}) == [
        "cyber.hexstrike",
        "blue.active_response",
    ]
    assert permission_ids_for_tool("hexstrike_defensive", {"action": "threat_intel_lookup"}) == [
        "network.internet",
        "cyber.hexstrike",
        "blue.static_rules",
    ]


@pytest.mark.asyncio
async def test_security_role_persists_and_is_returned(jarvis_env, monkeypatch):
    task = Task(
        id="blue-task",
        title="Blue task",
        prompt="Inspect local evidence",
        status="queued",
        task_class="mixed",
        security_role="blue-team",
    )
    async with SessionLocal() as session:
        session.add(task)
        await session.commit()
    from app.db import session as session_module

    async with session_module.ENGINE.connect() as connection:
        columns = await connection.run_sync(lambda conn: {col["name"] for col in inspect(conn).get_columns("tasks")})
    assert "security_role" in columns
    monkeypatch.setattr("app.agent.tool_exposure.hexstrike_access_mode", lambda: "blue")
    payload = _task_dict(task)
    assert payload["security_role"] == "blue-team"
    assert "hexstrike_defensive" in payload["allowed_tools"]
    assert "hexstrike_defensive" in payload["exposed_tools"]
    task.security_role = ""
    payload = _task_dict(task)
    assert "hexstrike_defensive" not in payload["allowed_tools"]
    assert "hexstrike_defensive" not in payload["exposed_tools"]


def test_installer_reports_ready_only_for_reviewed_complete_install(tmp_path, monkeypatch):
    root = tmp_path / "hexstrike"
    (root / "hexstrike-env" / "Scripts").mkdir(parents=True)
    (root / "hexstrike_server.py").write_text("# pinned server\n", encoding="utf-8")
    (root / "hexstrike-env" / "Scripts" / "python.exe").write_bytes(b"")
    installer = HexStrikeInstaller()
    installer._status.install_path = str(root)
    monkeypatch.setattr(installer, "_installed_commit", lambda path: APPROVED_HEXSTRIKE_COMMIT)
    monkeypatch.setattr(installer, "_installed_remote", lambda path: APPROVED_HEXSTRIKE_REMOTE)
    monkeypatch.setattr(installer, "_source_clean", lambda path: True)
    status = installer.status()
    assert status.state == "ready"
    assert status.approved_commit == APPROVED_HEXSTRIKE_COMMIT


def test_bootstrapper_pins_source_commit_and_loopback():
    script = Path("scripts/bootstrap-hexstrike.ps1").read_text(encoding="utf-8")
    assert APPROVED_HEXSTRIKE_COMMIT in script
    assert APPROVED_HEXSTRIKE_REMOTE in script
    assert "$env:HEXSTRIKE_HOST = '127.0.0.1'" in script
    assert "Invoke-RestMethod -Uri \"http://127.0.0.1:$Port/health\"" in script
    assert "hexstrike_compat.py" in script
    assert "Get-NetTCPConnection -LocalPort $Port -State Listen" in script
    assert ".CommandLine.Contains($Compat)" in script


def test_launcher_disables_unshipped_proxy_dependency():
    launcher = Path("backend/app/security/hexstrike_compat.py").read_text(encoding="utf-8")
    requirements = Path("config/hexstrike-defensive-requirements.txt").read_text(encoding="utf-8")
    assert "proxy/browser extras are disabled" in launcher
    assert "mitmproxy" not in requirements
    assert 'app.run(host="0.0.0.0"' in launcher
    assert "app.run(host=API_HOST" in launcher
    assert "/tmp/hexstrike_envs" in launcher


def test_action_api_rejects_unknown_fields_before_execution(jarvis_env, allow_loopback_api):
    client = TestClient(app)
    response = client.post(
        "/api/hexstrike/actions",
        json={"action": "host_baseline", "scope_id": "host", "command": "whoami"},
    )
    assert response.status_code == 422


def test_status_api_includes_install_capabilities_dependencies_and_jobs(jarvis_env, monkeypatch, allow_loopback_api):
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.resolve_install", lambda explicit="": None)
    monkeypatch.setattr("app.security.hexstrike_defensive.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_payload", lambda now=None: {
        "access_mode": "full",
        "access_message": "",
        "operator_allowed": True,
        "blue_allowed": True,
    })
    client = TestClient(app)
    body = client.get("/api/hexstrike").json()
    assert body["install"]["approved_commit"] == APPROVED_HEXSTRIKE_COMMIT
    assert body["capabilities"]
    assert isinstance(body["missing_dependencies"], list)
    assert body["managed_jobs"] == list_jobs()
    assert "catalog" in body
    assert body["catalog_count"] >= len(body["capabilities"])


def test_defensive_operator_prompts_skip_conversation_lane():
    assert is_defensive_operator_prompt("Run a lan inventory with nmap on my subnet")
    assert not follow_up_stays_conversation("please scan containers with trivy", security_role="blue-team")
    assert follow_up_stays_conversation("how are you?", security_role="blue-team")
