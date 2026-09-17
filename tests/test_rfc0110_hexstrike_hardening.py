from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.policy.approval_pending import reset_pending_approval_state
from app.policy.computer_permissions import apply_grant, reset_computer_permission_state
from app.security.hexstrike import HEXSTRIKE
from app.security.hexstrike_operator import sync_operator_surface
from app.security.hexstrike_tools import (
    allowed_pip_package_names,
    install_dependency_by_id,
    install_pip_package,
)


@pytest.fixture
def hardened_env(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp)
    monkeypatch.setattr("app.policy.approval_pending.data_dir", lambda: tmp)
    monkeypatch.setattr("app.inference.security_gates.data_dir", lambda: tmp)
    monkeypatch.setattr("app.policy.cyber_ato.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.resolve_install", lambda explicit="": None)
    monkeypatch.setattr("app.security.hexstrike_operator.data_dir", lambda: tmp)
    monkeypatch.setattr("app.inference.security_gates.gate_is_enabled", lambda role: True)
    reset_computer_permission_state()
    reset_pending_approval_state()
    return jarvis_env


def test_operate_parks_without_grant_returns_428(hardened_env):
    client = TestClient(app)
    response = client.post(
        "/api/hexstrike/operate",
        json={"capability_id": "http:scanner_one", "arguments": {"mode": "inventory"}},
    )
    assert response.status_code == 428
    body = response.json()
    detail = body["detail"]
    assert detail["status"] == "pending_approval"
    assert detail["permission_id"] == "cyber.hexstrike"
    assert detail["options"] == ["allow_once", "always", "deny"]
    assert detail["context"]["capability_id"] == "http:scanner_one"

    pending = client.get("/api/approvals/pending")
    assert pending.status_code == 200
    assert len(pending.json()["pending"]) == 1


def test_deny_does_not_execute_operate(hardened_env, monkeypatch):
    operate_called = {"value": False}

    async def fake_operate(*args, **kwargs):
        operate_called["value"] = True
        return {"id": "job-x"}

    monkeypatch.setattr("app.security.hexstrike_pending.operate", fake_operate)
    client = TestClient(app)
    parked = client.post(
        "/api/hexstrike/operate",
        json={"capability_id": "http:scanner_one", "arguments": {}},
    )
    pending_id = parked.json()["detail"]["pending_id"]
    denied = client.post(
        f"/api/approvals/pending/{pending_id}/decide",
        json={"mode": "deny", "owner_note": "not now"},
    )
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"
    assert denied.json()["executed"] is False
    assert operate_called["value"] is False


def test_allow_once_executes_then_reasks(hardened_env, monkeypatch, operator_store=None):
    tmp = hardened_env["tmp"]

    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(tmp),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)

    async def fake_operate(capability_id, arguments):
        return {"id": "job-1", "capability_id": capability_id, "status": "completed"}

    monkeypatch.setattr("app.security.hexstrike_pending.operate", fake_operate)
    client = TestClient(app)
    parked = client.post(
        "/api/hexstrike/operate",
        json={"capability_id": "http:scanner_one", "arguments": {"x": 1}},
    )
    pending_id = parked.json()["detail"]["pending_id"]
    approved = client.post(
        f"/api/approvals/pending/{pending_id}/decide",
        json={"mode": "allow_once", "owner_note": "go"},
    )
    assert approved.status_code == 200
    assert approved.json()["executed"] is True
    assert approved.json()["result"]["id"] == "job-1"

    second = client.post(
        "/api/hexstrike/operate",
        json={"capability_id": "http:scanner_one", "arguments": {"x": 2}},
    )
    assert second.status_code == 428


def test_always_allow_skips_reprompt(hardened_env, monkeypatch):
    apply_grant("cyber.hexstrike", "always")
    tmp = hardened_env["tmp"]

    async def fake_status(*, enrich=False):
        return SimpleNamespace(
            running=True,
            install_path=str(tmp),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)

    async def fake_operate(capability_id, arguments):
        return {"id": "job-2", "capability_id": capability_id, "status": "completed"}

    monkeypatch.setattr("app.api.hexstrike.operate", fake_operate)
    client = TestClient(app)
    response = client.post(
        "/api/hexstrike/operate",
        json={"capability_id": "http:scanner_one", "arguments": {}},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "job-2"


@pytest.mark.asyncio
async def test_status_poll_does_not_register_mcp(hardened_env, monkeypatch):
    tmp = hardened_env["tmp"]
    register_calls = {"count": 0}

    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(tmp),
            tools={"nmap": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
        )

    async def fake_register(**kwargs):
        register_calls["count"] += 1
        return SimpleNamespace(ok=True, as_dict=lambda: {"ok": True})

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr("app.security.hexstrike_operator.register_hexstrike_mcp", fake_register)
    monkeypatch.setattr(
        "app.security.hexstrike_operator.refresh_discovered_catalog",
        AsyncMock(return_value=[]),
    )
    await sync_operator_surface(register_mcp=False)
    assert register_calls["count"] == 0
    await sync_operator_surface(register_mcp=True)
    assert register_calls["count"] == 1


def test_status_get_uses_register_mcp_false(hardened_env, monkeypatch):
    calls: list[bool] = []

    async def fake_sync(*, register_mcp: bool = True):
        calls.append(register_mcp)
        return {"operator_ready": False, "catalog_count": 0, "mcp": {"ok": False}}

    async def fake_status():
        from app.security.hexstrike import HexStrikeStatus

        return HexStrikeStatus(
            suite="hexstrike-suite",
            shape_id="hex_aegis",
            installed=True,
            running=True,
            host="127.0.0.1",
            port=8888,
            install_path=str(hardened_env["tmp"]),
            python_executable="python",
            pid=1,
            last_error="",
            tools={},
        )

    monkeypatch.setattr("app.api.hexstrike.sync_operator_surface", fake_sync)
    monkeypatch.setattr("app.api.hexstrike.HEXSTRIKE.status", fake_status)
    client = TestClient(app)
    client.get("/api/hexstrike")
    assert calls == [False]


@pytest.mark.asyncio
async def test_pip_install_rejects_arbitrary_package(hardened_env, monkeypatch):
    monkeypatch.setattr(
        "app.security.hexstrike_tools.resolve_install",
        lambda explicit="": hardened_env["tmp"] / "hexstrike-ai",
    )
    (hardened_env["tmp"] / "hexstrike-ai").mkdir()
    (hardened_env["tmp"] / "hexstrike-ai" / "requirements.txt").write_text("requests\n", encoding="utf-8")
    assert "requests" in allowed_pip_package_names(str(hardened_env["tmp"] / "hexstrike-ai"))
    result = await install_pip_package("evil-package", install_path=str(hardened_env["tmp"] / "hexstrike-ai"))
    assert result.ok is False
    assert "allowlist" in result.detail.lower()


@pytest.mark.asyncio
async def test_pip_install_requires_hexstrike_python_not_sys_executable(hardened_env):
    result = await install_dependency_by_id("pip:requests", install_path="")
    assert result.ok is False
    assert "hexstrike" in result.detail.lower()
    assert "sys.executable" not in result.detail.lower()


def test_tool_install_parks_instead_of_auto_session(hardened_env):
    client = TestClient(app)
    response = client.post("/api/hexstrike/tools/nmap/install")
    assert response.status_code == 428
    assert response.json()["detail"]["action_kind"] == "hexstrike.tool.install"
