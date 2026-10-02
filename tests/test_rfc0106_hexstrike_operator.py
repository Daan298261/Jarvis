from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.hexstrike import HEXSTRIKE, operator_post_allowed
from app.security.hexstrike_install import APPROVED_HEXSTRIKE_COMMIT, APPROVED_HEXSTRIKE_REMOTE
from app.security.hexstrike_mcp import (
    HEXSTRIKE_MCP_SERVER_NAME,
    build_hexstrike_mcp_server,
    register_hexstrike_mcp,
)
from app.security.hexstrike_operator import (
    artifact_path_allowed,
    discovered_catalog,
    job_directory,
    operate,
    refresh_discovered_catalog,
    stop_operator_job,
)
from app.tools.hexstrike_operator import HexStrikeOperatorTool
from app.agent import tool_exposure

@pytest.fixture
def operator_store(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.security.hexstrike_operator.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike_operator.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    # Align process flags with mocked status(running=True) so catalog honesty matches.
    HEXSTRIKE._process = SimpleNamespace(pid=1, returncode=None)
    HEXSTRIKE._loopback_healthy = True
    yield tmp
    HEXSTRIKE._process = None
    HEXSTRIKE._loopback_healthy = False
    HEXSTRIKE._health = {}



@pytest.mark.asyncio
async def test_discovered_catalog_includes_http_tools_beyond_defensive_enums(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"nmap": "ok", "custom_tool_alpha": "missing", "custom_tool_beta": "ready"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    catalog = await refresh_discovered_catalog(force=True)
    ids = {item["id"] for item in catalog}
    assert "http:custom_tool_alpha" in ids
    assert "http:custom_tool_beta" in ids
    assert len(ids) > 6


@pytest.mark.asyncio
async def test_mcp_registration_hook_builds_loopback_server_and_refreshes_runtime(operator_store, monkeypatch):
    install = operator_store / "hexstrike-ai"
    install.mkdir()
    (install / "hexstrike_mcp.py").write_text("# mcp entry\n", encoding="utf-8")
    refreshed: dict[str, list] = {}

    async def fake_refresh(servers):
        refreshed["servers"] = servers
        return {"hexstrike-upstream": "3 tools"}

    monkeypatch.setattr("app.security.hexstrike_mcp.MCP.refresh", fake_refresh)
    result = await register_hexstrike_mcp(
        install_path=install,
        python_executable="python",
        host="127.0.0.1",
        port=8888,
    )
    assert result.ok is True
    stdio = refreshed["servers"][0]
    assert stdio["transport"] == "stdio"
    assert "--stdio" in stdio["args"]
    assert "--server" in stdio["args"]
    assert "127.0.0.1:8888" in stdio["args"][stdio["args"].index("--server") + 1]


def test_mcp_registration_refuses_non_loopback_host(operator_store):
    servers = build_hexstrike_mcp_server(
        install_path=operator_store,
        python_executable="python",
        host="0.0.0.0",
        port=8888,
    )
    assert servers == []


def test_operator_post_allowlist_keeps_blocked_tokens():
    assert operator_post_allowed("api/tools/nmap")
    assert not operator_post_allowed("api/command")
    assert not operator_post_allowed("api/tools/payload-builder")


@pytest.mark.asyncio
async def test_operate_creates_job_and_uses_post_operator(operator_store, monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "app.security.hexstrike_operator.audit_hexstrike",
        lambda action, **fields: events.append((action, fields)),
    )

    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    await refresh_discovered_catalog(force=True)

    async def fake_post(path, payload):
        assert path == "api/tools/scanner_one"
        assert payload == {"mode": "inventory"}
        return {"pid": 9911, "status": "started"}

    monkeypatch.setattr(HEXSTRIKE, "post_operator", fake_post)
    job = await operate("http:scanner_one", {"mode": "inventory"})
    assert job["status"] == "succeeded"
    assert job["upstream_pid"] == 9911
    assert (operator_store / "hexstrike" / "jobs" / job["id"] / "result.json").is_file()
    assert any(action == "operate_started" for action, _ in events)


@pytest.mark.asyncio
async def test_stop_operator_job_only_stops_tracked_pids(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    await refresh_discovered_catalog(force=True)

    async def fake_post(path, payload):
        return {"pid": 1234, "status": "started"}

    monkeypatch.setattr(HEXSTRIKE, "post_operator", fake_post)
    job = await operate("http:scanner_one", {"mode": "inventory"})
    stopped = await stop_operator_job(job["id"])
    assert stopped["status"] == "cancelled"
    untracked = dict(job)
    untracked["id"] = "bbbbbbbb-bbbb-4ccc-dddd-bbbbbbbbbbbb"
    untracked["upstream_pid"] = None
    from app.security.hexstrike_operator import _save_job

    _save_job(untracked)
    with pytest.raises(PermissionError):
        await stop_operator_job(untracked["id"])


def test_artifact_paths_stay_within_job_or_allowed_roots(operator_store, jarvis_env):
    job_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    directory = job_directory(job_id)
    inside = directory / "report.json"
    inside.write_text("{}", encoding="utf-8")
    assert artifact_path_allowed(inside)
    outside = Path("/tmp/jarvis-rfc0106-unrelated-outside/outside.txt")
    assert not artifact_path_allowed(outside)


def test_hexstrike_operator_api_routes(jarvis_env, monkeypatch, operator_store, allow_loopback_api):
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.resolve_install", lambda explicit="": None)
    monkeypatch.setattr("app.security.hexstrike_operator.data_dir", lambda: operator_store)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    client = TestClient(app)
    tools = client.get("/api/hexstrike/tools")
    assert tools.status_code == 200
    body = tools.json()
    assert body["count"] >= 6
    assert "catalog" in body


def test_hexstrike_operator_tool_exposed_via_capability_alias(monkeypatch):
    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda: "full")
    names = tool_exposure.tool_names_for("filesystem", ["hexstrike"])
    assert "hexstrike_operator" in names


@pytest.mark.asyncio
async def test_hexstrike_operator_chat_tool_runs_operate(monkeypatch, operator_store):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    monkeypatch.setattr(
        "app.tools.hexstrike_operator.evaluate_permission",
        lambda permission: SimpleNamespace(status="allow"),
    )

    async def fake_operate(capability_id, arguments):
        return {"id": "job-1", "capability_id": capability_id, "status": "succeeded", "error": "", "daybreak_jobs_hint": "Open Daybreak → Jobs for job job-1"}

    monkeypatch.setattr("app.tools.hexstrike_operator.operate", fake_operate)
    tool = HexStrikeOperatorTool(lambda: {})
    result = await tool.execute(operation="operate", capability_id="http:alpha", arguments={"x": 1})
    assert result.success is True
    assert "Daybreak" in (result.data or {}).get("daybreak_jobs_hint", "")


@pytest.mark.asyncio
async def test_operate_rejects_dependency_catalog_rows(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
        )

    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    # Guaranteed-missing host tool — do not assume the CI/dev machine lacks nmap.
    import shutil as _shutil

    real_which = _shutil.which

    def _which_missing_nmap(name):
        if str(name).lower() == "nmap":
            return None
        return real_which(name)

    monkeypatch.setattr("app.security.hexstrike_operator.shutil.which", _which_missing_nmap)
    monkeypatch.setattr("app.security.hexstrike_tools.shutil.which", _which_missing_nmap)
    await refresh_discovered_catalog(force=True)
    with pytest.raises(ValueError, match="install via POST"):
        await operate("dep:nmap", {})


def test_install_pin_constants_unchanged():
    assert APPROVED_HEXSTRIKE_REMOTE == "https://github.com/0x4m4/hexstrike-ai.git"
    assert len(APPROVED_HEXSTRIKE_COMMIT) == 40


def _nmap_on_path(monkeypatch):
    import shutil as _shutil

    real_which = _shutil.which

    def _which(name, *args, **kwargs):
        if str(name).lower() == "nmap":
            return "/usr/bin/nmap"
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr("app.security.hexstrike_operator.shutil.which", _which)


@pytest.mark.asyncio
async def test_lan_inventory_catalog_available_when_suite_stopped(operator_store, monkeypatch):
    from app.security import hexstrike_operator as hop

    HEXSTRIKE._process = None
    HEXSTRIKE._loopback_healthy = False
    hop._CATALOG_CACHE = []
    _nmap_on_path(monkeypatch)

    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=False,
            install_path=str(operator_store),
            tools={},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=[],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    catalog = await refresh_discovered_catalog(force=True)
    lan = next(item for item in catalog if item["id"] == "defensive:lan_inventory")
    assert lan["available"] is True
    assert lan["input_schema"]["required"] == []
    host = next(item for item in catalog if item["id"] == "defensive:host_baseline")
    assert host["available"] is False

    hop._CATALOG_CACHE = []
    offline = discovered_catalog()
    lan_offline = next(item for item in offline if item["id"] == "defensive:lan_inventory")
    assert lan_offline["available"] is True


@pytest.mark.asyncio
async def test_operate_lan_inventory_empty_scope_starts_stopped_suite(operator_store, monkeypatch):
    from app.security import hexstrike_operator as hop

    HEXSTRIKE._process = None
    HEXSTRIKE._loopback_healthy = False
    hop._CATALOG_CACHE = []
    _nmap_on_path(monkeypatch)
    monkeypatch.setattr("app.security.hexstrike_defensive.data_dir", lambda: operator_store)
    monkeypatch.setattr(
        "app.security.hexstrike_defensive.discover_private_lan_cidrs",
        lambda: ["10.2.0.0/16"],
    )
    started = {"count": 0}

    async def fake_status(*, enrich=False):
        return SimpleNamespace(
            running=False,
            last_error="",
            install_path=str(operator_store),
            tools={},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=[],
        )

    async def fake_start():
        started["count"] += 1
        return SimpleNamespace(running=True, last_error="")

    async def fake_post(path, payload):
        assert path == "api/tools/nmap"
        assert payload["target"] == "10.2.0.0/16"
        return {"hosts": []}

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr(HEXSTRIKE, "ensure_started", fake_start)
    monkeypatch.setattr(HEXSTRIKE, "post_defensive", fake_post)
    await refresh_discovered_catalog(force=True)
    job = await operate("defensive:lan_inventory", {})
    assert job["status"] == "completed"
    assert started["count"] == 1
    assert job["result"]["scope_id"] == "lan"


@pytest.mark.asyncio
async def test_lan_inventory_catalog_available_when_suite_installed_without_host_nmap(
    operator_store, monkeypatch
):
    from app.security import hexstrike_operator as hop

    HEXSTRIKE._process = None
    HEXSTRIKE._loopback_healthy = False
    hop._CATALOG_CACHE = []

    import shutil as _shutil

    real_which = _shutil.which

    def _which_no_nmap(name, *args, **kwargs):
        if str(name).lower() == "nmap":
            return None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr("app.security.hexstrike_operator.shutil.which", _which_no_nmap)
    monkeypatch.setattr(
        HEXSTRIKE,
        "_base_status",
        lambda: SimpleNamespace(installed=True, running=False, optional_stubs=[]),
    )

    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=False,
            installed=True,
            install_path=str(operator_store),
            tools={},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=[],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    catalog = await refresh_discovered_catalog(force=True)
    lan = next(item for item in catalog if item["id"] == "defensive:lan_inventory")
    assert lan["available"] is True
    assert lan["missing_dependencies"] == []
