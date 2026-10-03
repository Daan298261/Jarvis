from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
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


async def test_threat_intel_lookup_honors_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state
    from app.security.hexstrike_defensive import _lookup_cve

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        return httpx.Response(200, json={"vulnerabilities": [{"cve": {"id": "CVE-2024-0001"}}]})

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr("app.policy.network_http.httpx.AsyncClient", Client)
    with pytest.raises(PermissionError):
        await _lookup_cve("CVE-2024-0001")
    assert seen["n"] == 0


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


@pytest.mark.asyncio
async def test_lan_inventory_accepts_legacy_scope_missing_from_target_registry(blue_store, monkeypatch):
    """HexStrike scopes saved before RFC-0197 have no security-targets.json row."""
    from app.security.target_registry import is_registered_value

    monkeypatch.setattr("app.security.target_registry.data_dir", lambda: blue_store)
    monkeypatch.setattr("app.security.security_audit.data_dir", lambda: blue_store)
    (blue_store / "hexstrike-scopes.json").write_text(
        json.dumps(
            {
                "version": 1,
                "scopes": [
                    {
                        "id": "legacy-lan",
                        "kind": "private_cidr",
                        "value": "192.168.20.0/24",
                        "label": "Home",
                        "attested_owned": True,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert is_registered_value("192.168.20.0/24") is False

    async def fake_status(*, enrich=False):
        return SimpleNamespace(running=True, last_error="")

    async def fake_post(path, payload):
        assert payload["target"] == "192.168.20.0/24"
        return {"hosts": [{"ip": "192.168.20.10"}]}

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr(HEXSTRIKE, "post_defensive", fake_post)
    job = await execute_defensive("lan_inventory", "legacy-lan")
    assert job["status"] == "completed"
    assert is_registered_value("192.168.20.0/24") is True


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


def test_preferred_lan_cidrs_put_gateway_subnet_before_vpn(monkeypatch):
    from app.security.hexstrike_defensive import preferred_lan_cidrs

    monkeypatch.setattr(
        "app.security.hexstrike_defensive.discover_private_lan_cidrs",
        lambda: ["10.8.0.0/24", "192.168.1.0/24"],
    )
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    assert preferred_lan_cidrs() == ["192.168.1.0/24", "10.8.0.0/24"]


def _home_vpn_addrs():
    import socket

    return {
        "eth0": [
            SimpleNamespace(family=socket.AF_INET, address="192.168.1.12", netmask="255.255.255.0"),
        ],
        "wg0": [
            SimpleNamespace(family=socket.AF_INET, address="10.8.0.2", netmask="255.255.255.0"),
        ],
        "wwan0": [
            SimpleNamespace(family=socket.AF_INET, address="100.64.1.8", netmask="255.192.0.0"),
        ],
        "Ethernet 2": [
            SimpleNamespace(family=socket.AF_INET, address="192.168.50.8", netmask="255.255.255.0"),
        ],
    }


def test_lan_scan_bind_pins_home_nic_not_vpn_or_cgnat(monkeypatch):
    from app.security.hexstrike_defensive import lan_scan_bind, nmap_lan_additional_args, nmap_lan_bind_args

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    assert lan_scan_bind("192.168.1.0/24") == ("eth0", "192.168.1.12")
    assert lan_scan_bind("192.168.1.50") == ("eth0", "192.168.1.12")
    assert lan_scan_bind("10.8.0.0/24") == ("wg0", "10.8.0.2")
    assert lan_scan_bind("8.8.8.0/24") == ("", "")
    assert lan_scan_bind("100.64.0.0/10") == ("", "")
    assert nmap_lan_bind_args("192.168.1.0/24") == ["-S", "192.168.1.12", "-e", "eth0"]
    assert nmap_lan_additional_args("192.168.1.0/24") == "-T3 -S 192.168.1.12 -e eth0"
    # Windows "Ethernet 2" has a space: host argv keeps -e; suite string omits it so HexStrike cannot split the name.
    assert nmap_lan_bind_args("192.168.50.0/24") == ["-S", "192.168.50.8", "-e", "Ethernet 2"]
    assert nmap_lan_additional_args("192.168.50.0/24") == "-T3 -S 192.168.50.8"


def test_lan_bind_nic_resolves_mdns_host_to_home_nic(monkeypatch):
    import socket

    from app.security.hexstrike_defensive import lan_bind_nic

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)

    def fake_getaddrinfo(host, *args, **kwargs):
        if host in {"nas.local", "router.lan"}:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    assert lan_bind_nic("nas.local") == ("eth0", "192.168.1.12")
    assert lan_bind_nic("http://router.lan/admin") == ("eth0", "192.168.1.12")
    assert lan_bind_nic("192.168.1.50") == ("eth0", "192.168.1.12")


@pytest.mark.asyncio
async def test_lan_inventory_uses_host_nmap_when_windows_nic_name_has_space(blue_store, monkeypatch):
    from app.security.hexstrike_defensive import lan_inventory_uses_host_nmap

    upsert_scope("wifi", kind="private_cidr", value="192.168.50.0/24", label="Wi-Fi", attested_owned=True)
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    assert lan_inventory_uses_host_nmap("192.168.50.0/24") is True
    assert lan_inventory_uses_host_nmap("192.168.1.0/24") is False

    async def fake_status(*, enrich=False):
        return SimpleNamespace(running=True, last_error="")

    async def fake_post(path, payload):
        raise AssertionError(f"HexStrike nmap must not receive a spaced NIC name: {payload}")

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr(HEXSTRIKE, "post_defensive", fake_post)
    monkeypatch.setattr(
        "app.security.hexstrike_defensive.shutil.which",
        lambda name, *args, **kwargs: "/usr/bin/nmap" if str(name).lower() == "nmap" else None,
    )

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"Nmap scan report for nas (192.168.50.12)\nHost is up.\n", b"")

        def kill(self):
            return None

        async def wait(self):
            return 0

    seen: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        seen.append(args)
        assert args[0] == "/usr/bin/nmap"
        assert args[args.index("-S") + 1] == "192.168.50.8"
        assert args[args.index("-e") + 1] == "Ethernet 2"
        return FakeProc()

    monkeypatch.setattr("app.security.hexstrike_defensive.asyncio.create_subprocess_exec", fake_exec)
    job = await execute_defensive("lan_inventory", "wifi")
    assert job["status"] == "completed"
    assert job["result"]["source"] == "host-nmap"
    assert job["result"]["hosts"][0]["address"] == "192.168.50.12"
    assert seen


def test_default_lan_scope_prefers_home_lan_and_registers_vpn_cidr(blue_store, monkeypatch):
    from app.security.hexstrike_defensive import (
        extra_lan_scope_id,
        ensure_default_lan_scope,
        lan_inventory_targets,
        list_scopes,
        upsert_scope,
    )

    monkeypatch.setattr(
        "app.security.hexstrike_defensive.discover_private_lan_cidrs",
        lambda: ["10.8.0.0/24", "192.168.1.0/24"],
    )
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    upsert_scope("lan", kind="private_cidr", value="10.8.0.0/24", label="VPN", attested_owned=True)
    refreshed = ensure_default_lan_scope()
    assert refreshed["value"] == "192.168.1.0/24"
    extra_id = extra_lan_scope_id("10.8.0.0/24")
    extras = {row["id"]: row["value"] for row in list_scopes()}
    assert extras[extra_id] == "10.8.0.0/24"
    assert lan_inventory_targets(refreshed) == ["192.168.1.0/24", "10.8.0.0/24"]


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


def test_default_lan_scope_refreshes_stale_or_public_cidr(blue_store, monkeypatch):
    from app.security.hexstrike_defensive import ensure_default_lan_scope, upsert_scope

    monkeypatch.setattr(
        "app.security.hexstrike_defensive.discover_private_lan_cidrs",
        lambda: ["192.168.20.0/24"],
    )
    upsert_scope("lan", kind="private_cidr", value="10.0.0.0/24", label="Old house", attested_owned=True)
    refreshed = ensure_default_lan_scope()
    assert refreshed["value"] == "192.168.20.0/24"
    (blue_store / "hexstrike-scopes.json").write_text(
        json.dumps(
            {
                "version": 1,
                "scopes": [
                    {
                        "id": "lan",
                        "kind": "private_cidr",
                        "value": "8.8.8.0/24",
                        "label": "Poisoned",
                        "attested_owned": True,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    repaired = ensure_default_lan_scope()
    assert repaired["value"] == "192.168.20.0/24"
    kept = ensure_default_lan_scope()
    assert kept["value"] == "192.168.20.0/24"


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
async def test_host_nmap_refuses_public_and_hostname_targets(monkeypatch):
    from app.security.hexstrike_defensive import _host_nmap_ping_scan

    called = {"n": 0}

    async def fake_exec(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("nmap must not run for a public target")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    with pytest.raises(ValueError, match="public"):
        await _host_nmap_ping_scan("8.8.8.0/24")
    with pytest.raises(ValueError):
        await _host_nmap_ping_scan("scanme.nmap.org")
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_lan_inventory_refuses_tampered_public_scope(blue_store, monkeypatch):
    (blue_store / "hexstrike-scopes.json").write_text(
        json.dumps(
            {
                "version": 1,
                "scopes": [
                    {
                        "id": "evil",
                        "kind": "private_cidr",
                        "value": "8.8.8.0/24",
                        "label": "Not LAN",
                        "attested_owned": True,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    called = {"n": 0}

    async def fake_exec(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("nmap must not run")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    with pytest.raises(PermissionError, match="public"):
        await execute_defensive("lan_inventory", "evil")
    assert called["n"] == 0


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
        assert args[args.index("-S") + 1] == "192.168.20.5"
        assert args[args.index("-e") + 1] == "wlan0"
        return FakeProc()

    monkeypatch.setattr(
        "psutil.net_if_addrs",
        lambda: {
            "wlan0": [
                SimpleNamespace(family=__import__("socket").AF_INET, address="192.168.20.5", netmask="255.255.255.0"),
            ],
            "wg0": [
                SimpleNamespace(family=__import__("socket").AF_INET, address="10.8.0.2", netmask="255.255.255.0"),
            ],
        },
    )
    monkeypatch.setattr("app.security.hexstrike_defensive.asyncio.create_subprocess_exec", fake_exec)
    job = await execute_defensive("lan_inventory", "lan")
    assert job["status"] == "completed"
    assert job["result"]["source"] == "host-nmap"
    assert job["result"]["hosts"][0]["address"] == "192.168.20.12"


@pytest.mark.asyncio
async def test_lan_inventory_suite_nmap_binds_home_nic(blue_store, monkeypatch):
    upsert_scope("lan", kind="private_cidr", value="192.168.1.0/24", label="Home", attested_owned=True)

    async def fake_status(*, enrich=False):
        return SimpleNamespace(running=True, last_error="")

    seen: list[dict] = []

    async def fake_post(path, payload):
        assert path == "api/tools/nmap"
        seen.append(payload)
        return {"hosts": []}

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    monkeypatch.setattr("app.security.hexstrike_defensive.discover_private_lan_cidrs", lambda: ["192.168.1.0/24", "10.8.0.0/24"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr(HEXSTRIKE, "post_defensive", fake_post)
    job = await execute_defensive("lan_inventory", "lan")
    assert job["status"] == "completed"
    assert [item["target"] for item in seen] == ["192.168.1.0/24", "10.8.0.0/24"]
    assert seen[0]["additional_args"] == "-T3 -S 192.168.1.12 -e eth0"
    assert seen[1]["additional_args"] == "-T3 -S 10.8.0.2 -e wg0"


def test_bind_hexstrike_nmap_payload_pins_lan_and_skips_public(monkeypatch):
    from app.security.hexstrike_defensive import bind_hexstrike_nmap_payload

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    lan = bind_hexstrike_nmap_payload({"target": "192.168.1.0/24", "scan_type": "-sV"})
    assert lan["additional_args"] == "-T3 -S 192.168.1.12 -e eth0"
    assert lan["scan_type"] == "-sV"
    spaced = bind_hexstrike_nmap_payload({"target": "192.168.50.12", "additional_args": "-T4"})
    assert spaced["additional_args"] == "-T4 -S 192.168.50.8"
    public = bind_hexstrike_nmap_payload({"target": "8.8.8.8", "additional_args": "-T3"})
    assert public["additional_args"] == "-T3"
    host_alias = bind_hexstrike_nmap_payload({"host": "192.168.1.40", "additional_args": "-T4"})
    assert host_alias["additional_args"] == "-T4 -S 192.168.1.12 -e eth0"


def test_bind_hexstrike_lan_payload_pins_nuclei_httpx_naabu(monkeypatch):
    from app.security.hexstrike_defensive import bind_hexstrike_lan_payload, bindable_lan_host

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    assert bindable_lan_host("http://192.168.1.40:8080/login") == "192.168.1.40"
    nuclei = bind_hexstrike_lan_payload(
        "http:nuclei",
        {"url": "http://192.168.1.40:8080/login", "additional_args": "-t http/"},
    )
    assert nuclei["additional_args"] == "-t http/ -source-ip 192.168.1.12 -interface eth0"
    assert nuclei["url"] == "http://192.168.1.40:8080/login"
    httpx = bind_hexstrike_lan_payload("mcp_hexstrike_ai_httpx", {"target": "192.168.1.0/24"})
    assert httpx["additional_args"] == "-source-ip 192.168.1.12 -interface eth0"
    naabu = bind_hexstrike_lan_payload("api/tools/naabu", {"host": "192.168.50.12", "extra_args": "-p 80"})
    assert naabu["extra_args"] == "-p 80 -source-ip 192.168.50.8"
    masscan = bind_hexstrike_lan_payload("masscan", {"target": "192.168.1.0/24"})
    assert masscan["additional_args"] == "--source-ip 192.168.1.12 -e eth0"
    curl = bind_hexstrike_lan_payload("curl", {"url": "http://192.168.1.1/"})
    assert curl["additional_args"] == "--interface eth0"
    public = bind_hexstrike_lan_payload("nuclei", {"target": "https://example.com", "additional_args": "-t cves/"})
    assert public["additional_args"] == "-t cves/"
    gobuster = bind_hexstrike_lan_payload("http:gobuster", {"url": "http://192.168.1.40/", "additional_args": "-w wordlist.txt"})
    assert gobuster["additional_args"].startswith("-w wordlist.txt --proxy http://127.0.0.1:")
    ffuf = bind_hexstrike_lan_payload("ffuf", {"url": "http://192.168.1.40/FUZZ", "additional_args": "-w wordlist.txt -p POST"})
    assert ffuf["additional_args"].startswith("-w wordlist.txt -p POST -x http://127.0.0.1:")
    dirsearch = bind_hexstrike_lan_payload("api/tools/dirsearch", {"url": "http://192.168.1.1/"})
    assert dirsearch["additional_args"].startswith("--proxy http://127.0.0.1:")
    already_proxy = bind_hexstrike_lan_payload(
        "gobuster",
        {"url": "http://192.168.1.40/", "additional_args": "-w w.txt --proxy http://127.0.0.1:9"},
    )
    assert already_proxy["additional_args"] == "-w w.txt --proxy http://127.0.0.1:9"
    public_bust = bind_hexstrike_lan_payload("gobuster", {"url": "https://example.com/", "additional_args": "-w w.txt"})
    assert public_bust["additional_args"] == "-w w.txt"
    already = bind_hexstrike_lan_payload(
        "nuclei",
        {"target": "192.168.1.40", "additional_args": "-source-ip 192.168.1.12"},
    )
    assert already["additional_args"] == "-source-ip 192.168.1.12"
    wget = bind_hexstrike_lan_payload("wget", {"url": "ftp://192.168.1.40/backup.tar"})
    assert wget["additional_args"] == "--bind-address=192.168.1.12"
    rustscan = bind_hexstrike_lan_payload("rustscan", {"target": "192.168.1.0/24", "additional_args": "-a 192.168.1.0/24"})
    assert rustscan["additional_args"] == "-a 192.168.1.0/24 -- -S 192.168.1.12 -e eth0"
    katana = bind_hexstrike_lan_payload("http:katana", {"url": "http://192.168.1.40/", "additional_args": "-jc"})
    assert katana["additional_args"].startswith("-jc -proxy http://127.0.0.1:")
    whatweb = bind_hexstrike_lan_payload("whatweb", {"url": "http://192.168.1.1/"})
    assert whatweb["additional_args"].startswith("--proxy 127.0.0.1:")
    wpscan = bind_hexstrike_lan_payload("wpscan", {"url": "http://192.168.1.40/"})
    assert wpscan["additional_args"].startswith("--proxy http://127.0.0.1:")
    public_katana = bind_hexstrike_lan_payload("katana", {"url": "https://example.com/"})
    assert public_katana.get("additional_args", "") == ""


def test_looks_like_nmap_tool_matches_hexstrike_mcp_ids():
    from app.security.hexstrike_defensive import looks_like_nmap_tool

    assert looks_like_nmap_tool("nmap")
    assert looks_like_nmap_tool("http:nmap")
    assert looks_like_nmap_tool("mcp_hexstrike_ai_nmap")
    assert looks_like_nmap_tool("mcp_hexstrike-ai_nmap")
    assert not looks_like_nmap_tool("mcp_hexstrike_ai_trivy")
    assert not looks_like_nmap_tool("container_scan")


def test_hexstrike_child_env_drops_proxy_so_lan_scans_are_not_stolen(monkeypatch):
    from app.security.hexstrike import hexstrike_child_env

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:8080")
    monkeypatch.setenv("https_proxy", "http://10.8.0.1:3128")
    monkeypatch.setenv("ALL_PROXY", "socks5://10.8.0.1:1080")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("JARVIS_HEXSTRIKE_HOME", "/opt/hexstrike")
    env = hexstrike_child_env()
    assert "HTTP_PROXY" not in env
    assert "https_proxy" not in env
    assert "ALL_PROXY" not in env
    assert "NO_PROXY" not in env
    assert env["JARVIS_HEXSTRIKE_HOME"] == "/opt/hexstrike"
    kept = hexstrike_child_env({"PATH": "/usr/bin", "http_proxy": "http://proxy.example:8080", "HEXSTRIKE_PORT": "8888"})
    assert "http_proxy" not in kept
    assert kept["PATH"] == "/usr/bin"
    assert kept["HEXSTRIKE_PORT"] == "8888"


def test_is_hexstrike_mcp_server_matches_upstream_and_script():
    from app.security.hexstrike import is_hexstrike_mcp_server

    assert is_hexstrike_mcp_server({"name": "hexstrike-upstream"})
    assert is_hexstrike_mcp_server({"name": "hexstrike-upstream-http"})
    assert is_hexstrike_mcp_server({"id": "hexstrike-ai"})
    assert is_hexstrike_mcp_server({"command": "python", "args": ["/opt/hexstrike-ai/hexstrike_mcp.py", "--stdio"]})
    assert not is_hexstrike_mcp_server({"name": "email", "command": "npx", "args": ["email-mcp"]})
    assert not is_hexstrike_mcp_server(None)


@pytest.mark.asyncio
async def test_mcp_nmap_call_binds_home_nic(monkeypatch):
    from app.tools.mcp_runtime import MCP

    seen: list[dict] = []

    class FakeSession:
        async def call_tool(self, name, arguments):
            seen.append({"name": name, "arguments": dict(arguments)})
            return SimpleNamespace(content="ok", is_error=False)

    async def fake_connect(server):
        return FakeSession()

    MCP.reset_for_tests()
    MCP._tools["mcp_hexstrike_ai_nmap"] = {
        "server": {"id": "hex", "name": "hexstrike-ai"},
        "tool": {"name": "nmap"},
        "remote_name": "nmap",
    }
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    monkeypatch.setattr(MCP, "_connect", fake_connect)
    try:
        result = await MCP.call("mcp_hexstrike_ai_nmap", {"target": "192.168.1.0/24"})
        assert result.success, result.error
        assert seen[0]["name"] == "nmap"
        assert seen[0]["arguments"]["additional_args"] == "-T3 -S 192.168.1.12 -e eth0"
    finally:
        MCP.reset_for_tests()


@pytest.mark.asyncio
async def test_mcp_nuclei_call_binds_home_nic(monkeypatch):
    from app.tools.mcp_runtime import MCP

    seen: list[dict] = []

    class FakeSession:
        async def call_tool(self, name, arguments):
            seen.append({"name": name, "arguments": dict(arguments)})
            return SimpleNamespace(content="ok", is_error=False)

    async def fake_connect(server):
        return FakeSession()

    MCP.reset_for_tests()
    MCP._tools["mcp_hexstrike_ai_nuclei"] = {
        "server": {"id": "hex", "name": "hexstrike-ai"},
        "tool": {"name": "nuclei"},
        "remote_name": "nuclei",
    }
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    monkeypatch.setattr(MCP, "_connect", fake_connect)
    try:
        result = await MCP.call(
            "mcp_hexstrike_ai_nuclei",
            {"url": "http://192.168.1.40/", "additional_args": "-t http/"},
        )
        assert result.success, result.error
        assert seen[0]["name"] == "nuclei"
        assert seen[0]["arguments"]["additional_args"] == "-t http/ -source-ip 192.168.1.12 -interface eth0"
        assert seen[0]["arguments"]["url"] == "http://192.168.1.40/"
    finally:
        MCP.reset_for_tests()


@pytest.mark.asyncio
async def test_mcp_nmap_uses_host_argv_when_windows_nic_name_has_space(monkeypatch):
    from app.tools.mcp_runtime import MCP

    async def fake_connect(server):
        raise AssertionError("MCP nmap must not be used when HexStrike would split -e")

    MCP.reset_for_tests()
    MCP._tools["mcp_hexstrike_ai_nmap"] = {
        "server": {"id": "hex", "name": "hexstrike-ai"},
        "tool": {"name": "nmap"},
        "remote_name": "nmap",
    }
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    monkeypatch.setattr(MCP, "_connect", fake_connect)
    monkeypatch.setattr(
        "app.security.hexstrike_defensive.shutil.which",
        lambda name, *args, **kwargs: "/usr/bin/nmap" if str(name).lower() == "nmap" else None,
    )

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"Nmap scan report for nas (192.168.50.12)\n", b"")

        def kill(self):
            return None

        async def wait(self):
            return 0

    seen: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        seen.append(args)
        return FakeProc()

    monkeypatch.setattr("app.security.hexstrike_defensive.asyncio.create_subprocess_exec", fake_exec)
    try:
        result = await MCP.call("mcp_hexstrike_ai_nmap", {"target": "192.168.50.0/24"})
        assert result.success, result.error
        assert result.data["source"] == "host-nmap"
        argv = seen[0]
        assert argv[argv.index("-e") + 1] == "Ethernet 2"
        assert argv[argv.index("-S") + 1] == "192.168.50.8"
        assert argv[-1] == "192.168.50.0/24"
    finally:
        MCP.reset_for_tests()


@pytest.mark.asyncio
async def test_operator_nmap_binds_home_nic(monkeypatch):
    from app.security.hexstrike_defensive import execute_operator_nmap

    seen: list[dict] = []

    async def fake_post(path, payload):
        assert path == "api/tools/nmap"
        seen.append(payload)
        return {"hosts": []}

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    monkeypatch.setattr(HEXSTRIKE, "post_operator", fake_post)
    result = await execute_operator_nmap({"target": "192.168.1.40", "scan_type": "-sV", "ports": "22,80"})
    assert result == {"hosts": []}
    assert seen[0]["target"] == "192.168.1.40"
    assert seen[0]["additional_args"] == "-T3 -S 192.168.1.12 -e eth0"
    assert seen[0]["scan_type"] == "-sV"


@pytest.mark.asyncio
async def test_operator_nmap_uses_host_argv_when_windows_nic_name_has_space(monkeypatch):
    from app.security.hexstrike_defensive import execute_operator_nmap

    async def fake_post(path, payload):
        raise AssertionError(f"HexStrike nmap must not receive a spaced NIC name: {payload}")

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_addrs)
    monkeypatch.setattr(HEXSTRIKE, "post_operator", fake_post)
    monkeypatch.setattr(
        "app.security.hexstrike_defensive.shutil.which",
        lambda name, *args, **kwargs: "/usr/bin/nmap" if str(name).lower() == "nmap" else None,
    )

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"Nmap scan report for printer (192.168.50.20)\nHost is up.\n", b"")

        def kill(self):
            return None

        async def wait(self):
            return 0

    seen: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        seen.append(args)
        return FakeProc()

    monkeypatch.setattr("app.security.hexstrike_defensive.asyncio.create_subprocess_exec", fake_exec)
    result = await execute_operator_nmap(
        {"target": "192.168.50.0/24", "scan_type": "-sT", "ports": "80,443", "additional_args": "-T4"}
    )
    assert result["source"] == "host-nmap"
    assert result["hosts"][0]["address"] == "192.168.50.20"
    argv = seen[0]
    assert argv[0] == "/usr/bin/nmap"
    assert "-sT" in argv
    assert "-T4" in argv
    assert argv[argv.index("-S") + 1] == "192.168.50.8"
    assert argv[argv.index("-e") + 1] == "Ethernet 2"
    assert argv[argv.index("-p") + 1] == "80,443"
    assert argv[-1] == "192.168.50.0/24"


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


@pytest.mark.asyncio
async def test_hexstrike_bootstrap_honors_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    ran = {"n": 0}

    async def boom(*_args, **_kwargs):
        ran["n"] += 1
        raise AssertionError("must not launch HexStrike bootstrap when internet is denied")

    monkeypatch.setattr("app.security.hexstrike_install.asyncio.create_subprocess_exec", boom)
    installer = HexStrikeInstaller()
    await installer._run(tmp_path / "hexstrike")
    assert ran["n"] == 0
    assert installer._status.state == "failed"
    assert installer._status.error


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
