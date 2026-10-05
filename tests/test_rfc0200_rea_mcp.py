"""RFC-0200 REA MCP path policy, LTA extract resolution, and registration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import app
from app.policy.computer_permissions import apply_grant, reset_computer_permission_state
from app.security.rea_mcp import (
    REA_AGENTS_PIN,
    REA_MCP_CATALOG_KEY,
    build_rea_mcp_server,
    enable_rea_mcp,
    grant_investigation_root,
    register_rea_mcp,
)
from app.security.rea_paths import (
    PATH_NOT_ALLOWED,
    PathNotAllowed,
    resolve_rea_investigation_path,
    sanitize_rea_mcp_arguments,
)
from app.tools.mcp_runtime import MCP
from app.tools.registry import REGISTRY
from app.tools.safety import resolve_allowed_path


@pytest.fixture
def rea_env(jarvis_env, monkeypatch):
    tmp: Path = jarvis_env["tmp"]
    settings: AppSettings = jarvis_env["settings"]
    settings.rea.enabled = True
    settings.rea.investigation_roots = []
    settings.allowed_directories = [str(tmp)]
    monkeypatch.setattr("app.security.rea_paths.load_settings", lambda: settings)
    monkeypatch.setattr("app.security.rea_mcp.load_settings", lambda: settings)
    monkeypatch.setattr("app.security.lta_archive.load_settings", lambda: settings)
    monkeypatch.setattr("app.security.lta_archive.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.rea_mcp.save_settings", lambda value: None)
    monkeypatch.delenv("REA_INVESTIGATION_INPUT_ROOTS_JSON", raising=False)
    monkeypatch.delenv("REA_PROCESS_EXECUTABLE_ROOTS_JSON", raising=False)
    monkeypatch.delenv("REA_PROCESS_WORKING_ROOTS_JSON", raising=False)
    monkeypatch.delenv("REA_BROWSER_SCENARIO_EXECUTABLE_ROOTS_JSON", raising=False)
    reset_computer_permission_state()
    yield {"tmp": tmp, "settings": settings}


def _write_succeeded_lta_job(tmp: Path, job_id: str = "aabbccddeeff") -> Path:
    extract = tmp / "lta-extract" / job_id / "files"
    extract.mkdir(parents=True)
    (extract / "sample.bin").write_bytes(b"artifact")
    index = tmp / "lta-extract" / "index.json"
    job = {
        "id": job_id,
        "status": "succeeded",
        "extract_dir": str(extract),
        "extract_listing": ["sample.bin"],
        "error": "",
    }
    index.write_text(json.dumps({"version": 1, "jobs": [job]}) + "\n", encoding="utf-8")
    return extract


def test_mcp_package_pins_rea_agents_exact_version():
    package = Path(__file__).resolve().parents[1] / "mcp" / "package.json"
    payload = json.loads(package.read_text(encoding="utf-8"))
    assert payload["dependencies"]["rea-agents"] == REA_AGENTS_PIN == "3.2.1"


def test_build_rea_mcp_server_uses_pinned_npx_stdio(rea_env):
    servers = build_rea_mcp_server()
    assert len(servers) == 1
    server = servers[0]
    assert server["name"] == "rea"
    assert server["catalog_key"] == REA_MCP_CATALOG_KEY == "io.github.morluto/rea"
    assert server["command"] == "npx"
    assert server["args"] == ["-y", f"rea-agents@{REA_AGENTS_PIN}", "mcp"]
    assert server["transport"] == "stdio"
    env = server["env"]
    assert json.loads(env["REA_INVESTIGATION_INPUT_ROOTS_JSON"]) == []
    assert env.get("REA_PROCESS_EXECUTABLE_ROOTS_JSON") == ""
    assert env.get("REA_PROCESS_WORKING_ROOTS_JSON") == ""
    assert env.get("REA_BROWSER_SCENARIO_EXECUTABLE_ROOTS_JSON") == ""


@pytest.mark.asyncio
async def test_register_rea_mcp_refreshes_runtime(rea_env, monkeypatch):
    captured: dict[str, list] = {}

    async def fake_refresh(servers):
        captured["servers"] = servers
        return {"rea": "4 tools"}

    monkeypatch.setattr("app.security.rea_mcp.MCP.refresh", fake_refresh)
    monkeypatch.setattr("app.security.rea_mcp.persist_rea_preset", lambda: None)
    result = await register_rea_mcp()
    assert result.ok is True
    stdio = captured["servers"][-1]
    assert stdio["args"] == ["-y", "rea-agents@3.2.1", "mcp"]
    assert stdio["catalog_key"] == REA_MCP_CATALOG_KEY


def test_empty_roots_deny_owner_path(rea_env):
    target = rea_env["tmp"] / "samples" / "app.exe"
    target.parent.mkdir()
    target.write_bytes(b"MZ")
    with pytest.raises(PathNotAllowed) as exc:
        resolve_rea_investigation_path(str(target))
    assert exc.value.code == PATH_NOT_ALLOWED
    assert exc.value.detail == "roots_empty"


def test_owner_path_requires_intersection(rea_env, monkeypatch):
    tmp: Path = rea_env["tmp"]
    samples = tmp / "samples"
    samples.mkdir()
    binary = samples / "app.exe"
    binary.write_bytes(b"MZ")
    outside_allowed = Path("/etc/passwd")
    monkeypatch.setenv("REA_INVESTIGATION_INPUT_ROOTS_JSON", json.dumps([str(samples), str(outside_allowed.parent)]))
    resolved = resolve_rea_investigation_path(str(binary))
    assert resolved == binary.resolve()
    with pytest.raises(PathNotAllowed):
        resolve_rea_investigation_path(str(outside_allowed))


def test_path_not_allowed_for_relative_and_null(rea_env, monkeypatch):
    monkeypatch.setenv("REA_INVESTIGATION_INPUT_ROOTS_JSON", json.dumps([str(rea_env["tmp"])]))
    with pytest.raises(PathNotAllowed) as relative:
        resolve_rea_investigation_path("relative/app.exe")
    assert relative.value.detail == "relative_path"
    with pytest.raises(PathNotAllowed):
        resolve_rea_investigation_path(str(rea_env["tmp"] / "a") + "\x00.exe")


def test_dotdot_escape_outside_roots(rea_env, monkeypatch):
    tmp: Path = rea_env["tmp"]
    samples = tmp / "samples"
    samples.mkdir()
    monkeypatch.setenv("REA_INVESTIGATION_INPUT_ROOTS_JSON", json.dumps([str(samples)]))
    escape = samples / ".." / "not-samples.bin"
    escape.write_bytes(b"x")
    with pytest.raises(PathNotAllowed) as exc:
        resolve_rea_investigation_path(str(escape))
    assert exc.value.code == PATH_NOT_ALLOWED


def test_lta_job_id_allowed_when_roots_empty(rea_env):
    extract = _write_succeeded_lta_job(rea_env["tmp"])
    resolved = resolve_rea_investigation_path(lta_job_id="aabbccddeeff")
    assert resolved == extract.parent.resolve()
    nested = resolve_rea_investigation_path(str(extract / "sample.bin"), lta_job_id="aabbccddeeff")
    assert nested == (extract / "sample.bin").resolve()


def test_explicit_path_under_lta_extract_when_roots_empty(rea_env):
    extract = _write_succeeded_lta_job(rea_env["tmp"])
    resolved = resolve_rea_investigation_path(str(extract / "sample.bin"))
    assert resolved == (extract / "sample.bin").resolve()


def test_lta_job_not_succeeded_is_denied(rea_env):
    job_id = "deadbeef0123"
    extract = rea_env["tmp"] / "lta-extract" / job_id / "files"
    extract.mkdir(parents=True)
    index = rea_env["tmp"] / "lta-extract" / "index.json"
    index.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [{"id": job_id, "status": "failed", "extract_dir": str(extract)}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PathNotAllowed) as exc:
        resolve_rea_investigation_path(lta_job_id=job_id)
    assert exc.value.detail == "lta_not_extracted"


def test_sanitize_mcp_arguments_rejects_outside_path(rea_env, monkeypatch):
    monkeypatch.setenv("REA_INVESTIGATION_INPUT_ROOTS_JSON", json.dumps([str(rea_env["tmp"] / "samples")]))
    (rea_env["tmp"] / "samples").mkdir()
    with pytest.raises(PathNotAllowed):
        sanitize_rea_mcp_arguments({"path": "/etc/passwd"})


@pytest.mark.asyncio
async def test_enable_rea_mcp_parks_without_grant(rea_env, monkeypatch):
    from app.policy.approval_pending import reset_pending_approval_state

    reset_pending_approval_state()
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: rea_env["tmp"])
    monkeypatch.setattr("app.policy.approval_pending.data_dir", lambda: rea_env["tmp"])
    result = await enable_rea_mcp(context={"source": "test"})
    assert result["status"] == "pending_approval"
    assert result["permission_id"] == "cyber.rea_mcp"


@pytest.mark.asyncio
async def test_enable_rea_mcp_registers_after_grant(rea_env, monkeypatch):
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: rea_env["tmp"])
    apply_grant("cyber.rea_mcp", "always")
    captured: dict[str, list] = {}

    async def fake_refresh(servers):
        captured["servers"] = servers
        return {"rea": "2 tools"}

    monkeypatch.setattr("app.security.rea_mcp.MCP.refresh", fake_refresh)
    monkeypatch.setattr("app.security.rea_mcp.persist_rea_preset", lambda: None)
    result = await enable_rea_mcp()
    assert result["enabled"] is True
    assert result["registration"]["ok"] is True
    assert captured["servers"][-1]["args"][1] == f"rea-agents@{REA_AGENTS_PIN}"


def test_grant_root_parks_then_intersects(rea_env, monkeypatch):
    from app.policy.approval_pending import reset_pending_approval_state

    reset_pending_approval_state()
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: rea_env["tmp"])
    monkeypatch.setattr("app.policy.approval_pending.data_dir", lambda: rea_env["tmp"])
    samples = rea_env["tmp"] / "samples"
    samples.mkdir()
    parked = grant_investigation_root(str(samples))
    assert parked["status"] == "pending_approval"
    apply_grant("cyber.rea_new_root", "always")
    granted = grant_investigation_root(str(samples))
    assert granted["ok"] is True
    assert Path(granted["root"]) == samples.resolve()
    with pytest.raises(PermissionError):
        grant_investigation_root("relative-root")


@pytest.mark.asyncio
async def test_tool_resolve_returns_path_not_allowed(rea_env):
    tool = REGISTRY.tools["rea_investigate"]
    result = await tool.execute(operation="resolve", path=str(rea_env["tmp"] / "nope.exe"))
    assert result.success is False
    assert result.error == PATH_NOT_ALLOWED


def test_lta_extract_root_api(rea_env, allow_loopback_api):
    extract = _write_succeeded_lta_job(rea_env["tmp"])
    client = TestClient(app)
    response = client.get("/api/lta/jobs/aabbccddeeff/extract-root")
    assert response.status_code == 200
    assert Path(response.json()["extract_root"]) == extract.parent.resolve()


def test_rea_resolve_api_empty_roots(rea_env, allow_loopback_api):
    client = TestClient(app)
    response = client.post("/api/rea/resolve", json={"path": str(rea_env["tmp"] / "x.bin")})
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == PATH_NOT_ALLOWED


def test_resolve_allowed_path_rejects_null_byte(tmp_path):
    with pytest.raises(PermissionError):
        resolve_allowed_path(str(tmp_path / "a") + "\x00.txt", [str(tmp_path)])
