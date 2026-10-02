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

    # RFC-0196: blue constant alone no longer unlocks HexStrike tools — hexstrike module → full.
    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda: HEXSTRIKE_ACCESS_BLUE)
    assert "hexstrike_defensive" not in tool_exposure.tool_names_for("mixed", ["hexstrike_defensive"])
    assert "hexstrike_operator" not in tool_exposure.tool_names_for("mixed", ["hexstrike"])

    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda: HEXSTRIKE_ACCESS_FULL)
    assert "hexstrike_defensive" in tool_exposure.tool_names_for("mixed", ["hexstrike_defensive"])
    assert "hexstrike_operator" in tool_exposure.tool_names_for("mixed", ["hexstrike"])


@pytest.mark.asyncio
async def test_defensive_tool_rechecks_role_gate_and_permissions(monkeypatch):
    context = {"security_role": ""}
    tool = HexStrikeDefensiveTool(lambda: context)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "locked")
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_denied_message",
        lambda now=None: "The installed license package does not include hexstrike.",
    )
    denied = await tool.execute(action="host_baseline", scope_id="host")
    assert denied.success is False
    assert "hexstrike" in (denied.error or "").lower()

    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
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
        "network.local",
    ]
    assert permission_ids_for_tool("hexstrike_defensive", {"action": "threat_intel_lookup"}) == [
        "network.internet",
        "cyber.hexstrike",
        "blue.static_rules",
    ]


@pytest.mark.asyncio
async def test_lan_inventory_does_not_require_hexstrike_suite_grant(monkeypatch):
    context = {"security_role": "blue-team"}
    tool = HexStrikeDefensiveTool(lambda: context)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")

    def eval_perm(permission):
        if permission == "cyber.hexstrike":
            return SimpleNamespace(status="ask")
        return SimpleNamespace(status="allow")

    monkeypatch.setattr("app.tools.hexstrike_defensive.evaluate_permission", eval_perm)

    async def fake_execute(action, scope_id, options):
        return {"id": "job", "action": action, "scope_id": scope_id, "status": "completed"}

    monkeypatch.setattr("app.tools.hexstrike_defensive.execute_defensive", fake_execute)
    allowed = await tool.execute(action="lan_inventory", scope_id="lan")
    assert allowed.success is True
    blocked = await tool.execute(action="host_baseline", scope_id="host")
    assert blocked.success is False
    assert "cyber.hexstrike" in (blocked.error or "")


@pytest.mark.asyncio
async def test_lan_inventory_starts_suite_without_hexstrike_grant(blue_store, monkeypatch):
    upsert_scope("lan", kind="private_cidr", value="192.168.20.0/24", label="Home", attested_owned=True)
    started = {"count": 0}

    async def fake_status(*, enrich=False):
        return SimpleNamespace(running=False, last_error="")

    async def fake_start():
        started["count"] += 1
        return SimpleNamespace(running=True, last_error="")

    async def fake_post(path, payload):
        assert path == "api/tools/nmap"
        assert payload["target"] == "192.168.20.0/24"
        return {"hosts": []}

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr(HEXSTRIKE, "ensure_started", fake_start)
    monkeypatch.setattr(HEXSTRIKE, "post_defensive", fake_post)
    job = await execute_defensive("lan_inventory", "lan")
    assert job["status"] == "completed"
    assert started["count"] == 1


def test_discover_private_lan_cidrs_skips_cgnat_and_public(monkeypatch):
    from types import SimpleNamespace

    import socket

    from app.security.hexstrike_defensive import discover_private_lan_cidrs

    def fake_addrs():
        return {
            "wlan0": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.20.12", netmask="255.255.255.0"),
            ],
            "wwan0": [
                SimpleNamespace(family=socket.AF_INET, address="100.64.1.8", netmask="255.192.0.0"),
            ],
            "eth0": [
                SimpleNamespace(family=socket.AF_INET, address="8.8.8.8", netmask="255.255.255.0"),
            ],
        }

    monkeypatch.setattr("psutil.net_if_addrs", fake_addrs)
    assert discover_private_lan_cidrs() == ["192.168.20.0/24"]


@pytest.mark.asyncio
async def test_lan_inventory_uses_nic_cidr_when_scope_missing(blue_store, monkeypatch):
    from types import SimpleNamespace

    import socket

    from app.security.hexstrike_defensive import discover_private_lan_cidrs, execute_defensive

    def fake_addrs():
        return {
            "wlan0": [
                SimpleNamespace(family=socket.AF_INET, address="10.2.0.5", netmask="255.255.0.0"),
            ],
        }

    monkeypatch.setattr("psutil.net_if_addrs", fake_addrs)
    assert discover_private_lan_cidrs() == ["10.2.0.0/16"]

    async def fake_status(*, enrich=False):
        return SimpleNamespace(running=True, last_error="")

    async def fake_post(path, payload):
        assert path == "api/tools/nmap"
        assert payload["target"] == "10.2.0.0/16"
        return {"hosts": []}

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr(HEXSTRIKE, "post_defensive", fake_post)
    job = await execute_defensive("lan_inventory", "")
    assert job["status"] == "completed"
    assert job["scope_id"] == "lan"


def test_parse_nmap_ping_hosts():
    from app.security.hexstrike_defensive import parse_nmap_ping_hosts

    hosts = parse_nmap_ping_hosts(
        "Nmap scan report for nas (192.168.20.12)\nHost is up.\n"
        "Nmap scan report for 192.168.20.1\n"
    )
    assert hosts == [
        {"address": "192.168.20.12", "hostname": "nas"},
        {"address": "192.168.20.1", "hostname": ""},
    ]


@pytest.mark.asyncio
async def test_lan_inventory_uses_host_nmap_when_suite_unavailable(blue_store, monkeypatch):
    upsert_scope("lan", kind="private_cidr", value="192.168.20.0/24", label="Home", attested_owned=True)

    async def fake_status(*, enrich=False):
        return SimpleNamespace(running=False, last_error="HexStrike AI is not installed.")

    async def fake_start():
        return SimpleNamespace(running=False, last_error="HexStrike AI is not installed.")

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr(HEXSTRIKE, "ensure_started", fake_start)
    monkeypatch.setattr(
        "app.security.hexstrike_defensive.shutil.which",
        lambda name, *args, **kwargs: "/usr/bin/nmap" if str(name).lower() == "nmap" else None,
    )

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"Nmap scan report for nas (192.168.20.12)\nHost is up.\n", b"")

        def kill(self):
            return None

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        assert args[0] == "/usr/bin/nmap"
        assert "-sn" in args
        assert args[-1] == "192.168.20.0/24"
        assert "--" in args
        return FakeProc()

    monkeypatch.setattr("app.security.hexstrike_defensive.asyncio.create_subprocess_exec", fake_exec)
    job = await execute_defensive("lan_inventory", "lan")
    assert job["status"] == "completed"
    assert job["result"]["source"] == "host-nmap"
    assert job["result"]["hosts"][0]["address"] == "192.168.20.12"


@pytest.mark.asyncio
async def test_operator_tool_lan_inventory_skips_suite_grant(jarvis_env, monkeypatch):
    from app.policy.computer_permissions import reset_computer_permission_state
    from app.tools.hexstrike_operator import HexStrikeOperatorTool

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: jarvis_env["tmp"])
    reset_computer_permission_state()
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")

    def eval_perm(permission):
        if permission == "cyber.hexstrike":
            return SimpleNamespace(status="ask", reason="HexStrike suite permission required")
        return SimpleNamespace(status="allow", reason="")

    monkeypatch.setattr("app.tools.hexstrike_operator.evaluate_permission", eval_perm)
    monkeypatch.setattr("app.policy.approval_pending.evaluate_permission", eval_perm)

    async def fake_operate(capability_id, arguments):
        return {"id": "job", "capability_id": capability_id, "status": "succeeded"}

    monkeypatch.setattr("app.tools.hexstrike_operator.operate", fake_operate)
    tool = HexStrikeOperatorTool(lambda: {})
    allowed = await tool.execute(
        operation="operate",
        capability_id="defensive:lan_inventory",
        arguments={"scope_id": "lan"},
    )
    assert allowed.success is True
    blocked = await tool.execute(operation="start")
    assert blocked.success is False
    assert blocked.error == "pending_approval"


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
    monkeypatch.setattr("app.agent.tool_exposure.hexstrike_access_mode", lambda: "full")
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
