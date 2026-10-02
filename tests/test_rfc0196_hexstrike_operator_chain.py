"""RFC-0196 HexStrike full operator chain — Anzu 1.0 quality bar."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.licensing.entitlements import (
    HEXSTRIKE_ACCESS_FULL,
    HEXSTRIKE_ACCESS_LOCKED,
    hexstrike_access_mode,
    hexstrike_access_payload,
    hexstrike_denied_message,
)
from app.main import app
from app.policy.cyber_ato import AtoStatus, licensed_module_allowed
from app.security.hexstrike import HEXSTRIKE, classify_loopback_http_error
from app.security.hexstrike_operator import (
    _CATALOG_CACHE,
    _save_job,
    artifact_path_allowed,
    get_operator_job,
    job_directory,
    list_operator_jobs,
    operate,
    refresh_discovered_catalog,
    stop_operator_job,
)
from app.tools.hexstrike_operator import HexStrikeOperatorTool


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
def operator_store(jarvis_env, monkeypatch):
    import app.security.hexstrike_operator as hop

    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.security.hexstrike_operator.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike_operator.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    monkeypatch.setattr(
        "app.licensing.entitlements.licensed_module_allowed",
        lambda module_id, now=None: str(module_id) == "hexstrike",
    )
    HEXSTRIKE._process = SimpleNamespace(pid=1, returncode=None)
    HEXSTRIKE._loopback_healthy = True
    hop._CATALOG_CACHE = []
    yield tmp
    HEXSTRIKE._process = None
    HEXSTRIKE._loopback_healthy = False
    HEXSTRIKE._health = {}
    hop._CATALOG_CACHE = []


def test_entitlement_deny_without_hexstrike_module(monkeypatch):
    status = _ato(modules=["blue-team"])
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    monkeypatch.setattr("app.licensing.entitlements.evaluate", lambda now=None: status)
    assert licensed_module_allowed("hexstrike") is False
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_LOCKED
    message = hexstrike_denied_message()
    assert "hexstrike" in message.lower()
    assert "password" not in message.lower()
    payload = hexstrike_access_payload()
    assert payload["operator_allowed"] is False
    assert "hexstrike" in payload["access_message"].lower()


def test_entitlement_full_when_hexstrike_module_present_without_le(monkeypatch):
    status = _ato(modules=["blue-team", "hexstrike"], law_enforcement=False)
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    monkeypatch.setattr("app.licensing.entitlements.evaluate", lambda now=None: status)
    assert licensed_module_allowed("hexstrike") is True
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_FULL
    assert hexstrike_access_payload()["operator_allowed"] is True


def test_suite_and_operate_deny_name_module(jarvis_env, monkeypatch, allow_loopback_api):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_access_payload",
        lambda now=None: {
            "access_mode": "locked",
            "access_message": "The installed license package does not include hexstrike.",
            "operator_allowed": False,
            "blue_allowed": False,
            "hexstrike_module": False,
        },
    )
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_denied_message",
        lambda now=None: "The installed license package does not include hexstrike.",
    )
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.resolve_install", lambda explicit="": None)
    client = TestClient(app)
    body = client.get("/api/hexstrike").json()
    assert body["access_mode"] == "locked"
    assert body["catalog"] == []
    assert "hexstrike" in body["access_message"].lower()
    start = client.post("/api/hexstrike/start")
    assert start.status_code == 403
    assert "hexstrike" in start.json()["detail"].lower()
    operate_resp = client.post(
        "/api/hexstrike/operate",
        json={"capability_id": "http:scanner_one", "arguments": {}},
    )
    assert operate_resp.status_code == 403
    assert "hexstrike" in operate_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_discovery_refresh_includes_all_sources_no_silent_cap(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={f"tool_{i}": "ok" for i in range(40)},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=[],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    catalog = await refresh_discovered_catalog(force=True)
    http_ids = [row["id"] for row in catalog if row["id"].startswith("http:")]
    assert len(http_ids) >= 40
    assert all(row.get("id") for row in catalog)
    # Pagination contract: full dump reports truncated=false
    client_tools = TestClient(app)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_access_payload",
        lambda now=None: {
            "access_mode": "full",
            "access_message": "",
            "operator_allowed": True,
            "blue_allowed": True,
            "hexstrike_module": True,
        },
    )
    # Avoid 503 from leftover MCP error during unit refresh
    monkeypatch.setattr("app.security.hexstrike_operator.mcp_registration_error", lambda: "")
    monkeypatch.setattr("app.security.hexstrike_operator.catalog_is_stale", lambda: False)
    page = client_tools.get("/api/hexstrike/tools?offset=0&limit=10")
    assert page.status_code == 200
    body = page.json()
    assert body["truncated"] is False
    assert body["count"] >= 40
    assert len(body["catalog"]) == 10
    assert body["has_more"] is True


@pytest.mark.asyncio
async def test_operate_creates_succeeded_job_shared_with_store(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=[],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    await refresh_discovered_catalog(force=True)

    async def fake_post(path, payload):
        assert path == "api/tools/scanner_one"
        return {"pid": 4242, "status": "started"}

    monkeypatch.setattr(HEXSTRIKE, "post_operator", fake_post)
    job = await operate("http:scanner_one", {"mode": "inventory"})
    assert job["status"] == "succeeded"
    assert job["daybreak_jobs_hint"]
    assert "Daybreak" in job["daybreak_jobs_hint"]
    stored = get_operator_job(job["id"])
    assert stored["id"] == job["id"]
    assert any(item["id"] == job["id"] for item in list_operator_jobs())
    assert (operator_store / "hexstrike" / "jobs" / job["id"] / "result.json").is_file()


@pytest.mark.asyncio
async def test_operate_failure_persists_failed_job_not_silent(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=[],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    await refresh_discovered_catalog(force=True)

    async def boom(path, payload):
        raise RuntimeError("HexStrike loopback connection refused (server not accepting connections on the configured port)")

    monkeypatch.setattr(HEXSTRIKE, "post_operator", boom)
    job = await operate("http:scanner_one", {})
    assert job["status"] == "failed"
    assert "refused" in job["error"].lower()
    assert get_operator_job(job["id"])["status"] == "failed"


@pytest.mark.asyncio
async def test_missing_claimed_artifact_marks_job_failed(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=[],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    await refresh_discovered_catalog(force=True)
    missing = operator_store / "hexstrike" / "jobs" / "ghost-report.json"

    async def fake_post(path, payload):
        return {"pid": 7, "artifact_paths": [str(missing)]}

    monkeypatch.setattr(HEXSTRIKE, "post_operator", fake_post)
    job = await operate("http:scanner_one", {})
    assert job["status"] == "failed"
    assert "missing artifact" in job["error"].lower()


@pytest.mark.asyncio
async def test_stop_operator_job_sets_cancelled(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=[],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    await refresh_discovered_catalog(force=True)

    async def fake_post(path, payload):
        if path.startswith("api/processes/terminate/"):
            return {"ok": True}
        return {"pid": 99, "status": "started"}

    monkeypatch.setattr(HEXSTRIKE, "post_operator", fake_post)
    job = await operate("http:scanner_one", {})
    stopped = await stop_operator_job(job["id"])
    assert stopped["status"] == "cancelled"


def test_loopback_error_honesty_taxonomy():
    assert "not running" in classify_loopback_http_error(RuntimeError("x"), suite_running=False).lower()
    refused = classify_loopback_http_error(
        httpx.ConnectError("Connection refused"),
        suite_running=True,
    )
    assert "refused" in refused.lower()
    timed = classify_loopback_http_error(httpx.ReadTimeout("timed out"), suite_running=True)
    assert "timed out" in timed.lower()


def test_artifact_path_bounds(operator_store, jarvis_env):
    job_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    directory = job_directory(job_id)
    inside = directory / "report.json"
    inside.write_text("{}", encoding="utf-8")
    assert artifact_path_allowed(inside)
    outside = Path("/tmp/jarvis-rfc0196-unrelated-outside/outside.txt")
    assert not artifact_path_allowed(outside)


@pytest.mark.asyncio
async def test_chat_tool_shares_job_store_and_daybreak_hint(operator_store, monkeypatch):
    monkeypatch.setattr(
        "app.tools.hexstrike_operator.evaluate_permission",
        lambda permission: SimpleNamespace(status="allow"),
    )

    async def fake_operate(capability_id, arguments):
        job = {
            "id": "job-chat-1",
            "capability_id": capability_id,
            "status": "succeeded",
            "daybreak_jobs_hint": "Open Daybreak → Jobs for job job-chat-1",
            "error": "",
        }
        _save_job(job)
        return job

    monkeypatch.setattr("app.tools.hexstrike_operator.operate", fake_operate)
    tool = HexStrikeOperatorTool(lambda: {})
    result = await tool.execute(operation="operate", capability_id="http:alpha", arguments={})
    assert result.success is True
    assert result.data["id"] == "job-chat-1"
    assert "Daybreak" in result.data["daybreak_jobs_hint"]
    assert get_operator_job("job-chat-1")["status"] == "succeeded"


def test_pin_and_loopback_guards_unchanged():
    from app.security.hexstrike import operator_post_allowed
    from app.security.hexstrike_install import APPROVED_HEXSTRIKE_COMMIT, APPROVED_HEXSTRIKE_REMOTE
    from app.security.hexstrike_mcp import build_hexstrike_mcp_server

    assert APPROVED_HEXSTRIKE_REMOTE == "https://github.com/0x4m4/hexstrike-ai.git"
    assert len(APPROVED_HEXSTRIKE_COMMIT) == 40
    assert operator_post_allowed("api/tools/nmap")
    assert not operator_post_allowed("api/command")
    assert build_hexstrike_mcp_server(
        install_path=Path("/tmp"),
        python_executable="python",
        host="0.0.0.0",
        port=8888,
    ) == []


def test_daybreak_hud_has_operate_jobs_and_module_copy():
    source = Path("frontend/src/hud/HudHexStrikeSuite.tsx").read_text(encoding="utf-8")
    assert "Operate" in source
    assert "Jobs" in source
    assert "hexstrike" in source.lower()
    assert "JOBS_POLL_MS = 2000" in source
    assert "Discovery failed" in source
    assert "License module" in source or "hexstrike module" in source.lower()
    assert "coming soon" not in source.lower()
    assert "TODO" not in source
