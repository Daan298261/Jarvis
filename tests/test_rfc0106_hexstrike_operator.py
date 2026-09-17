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
    monkeypatch.setattr("app.security.hexstrike.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    return tmp



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
        return {"hexstrike-upstream": "2 tools"}

    monkeypatch.setattr("app.security.hexstrike_mcp.MCP.refresh", fake_refresh)
    status = await register_hexstrike_mcp(
        install_path=install,
        python_executable="python",
        host="127.0.0.1",
        port=8888,
    )
    assert status
    names = {item.get("name") for item in refreshed["servers"]}
    assert HEXSTRIKE_MCP_SERVER_NAME in names
    assert any(str(item.get("url", "")).startswith("http://127.0.0.1:") for item in refreshed["servers"] if item.get("url"))


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
    assert job["status"] == "completed"
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
    assert stopped["status"] == "stopped"
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
    outside = operator_store / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    assert not artifact_path_allowed(outside)


def test_hexstrike_operator_api_routes(jarvis_env, monkeypatch, operator_store):
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.resolve_install", lambda explicit="": None)
    monkeypatch.setattr("app.security.hexstrike_operator.data_dir", lambda: operator_store)
    client = TestClient(app)
    tools = client.get("/api/hexstrike/tools")
    assert tools.status_code == 200
    body = tools.json()
    assert body["count"] >= 6
    assert "catalog" in body


def test_hexstrike_operator_tool_exposed_via_capability_alias(monkeypatch):
    monkeypatch.setattr(tool_exposure, "gate_is_enabled", lambda role: True)
    names = tool_exposure.tool_names_for("filesystem", ["hexstrike"])
    assert "hexstrike_operator" in names


@pytest.mark.asyncio
async def test_hexstrike_operator_chat_tool_runs_operate(monkeypatch, operator_store):
    monkeypatch.setattr(
        "app.tools.hexstrike_operator.evaluate_permission",
        lambda permission: SimpleNamespace(status="allow"),
    )

    async def fake_operate(capability_id, arguments):
        return {"id": "job-1", "capability_id": capability_id, "status": "completed"}

    monkeypatch.setattr("app.tools.hexstrike_operator.operate", fake_operate)
    tool = HexStrikeOperatorTool(lambda: {})
    result = await tool.execute(operation="operate", capability_id="http:alpha", arguments={"x": 1})
    assert result.success is True


def test_install_pin_constants_unchanged():
    assert APPROVED_HEXSTRIKE_REMOTE == "https://github.com/0x4m4/hexstrike-ai.git"
    assert len(APPROVED_HEXSTRIKE_COMMIT) == 40
