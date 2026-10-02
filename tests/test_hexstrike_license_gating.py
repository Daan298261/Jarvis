"""License-package HexStrike gating after RFC-0196 (module entitlement, not LE/password)."""
from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent import tool_exposure
from app.licensing.entitlements import (
    HEXSTRIKE_ACCESS_BLUE,
    HEXSTRIKE_ACCESS_FULL,
    HEXSTRIKE_ACCESS_LOCKED,
    HEXSTRIKE_OPERATOR_LICENSE_MESSAGE,
    hexstrike_access_mode,
    hexstrike_access_payload,
    hexstrike_denied_message,
)
from app.main import app
from app.policy.cyber_ato import AtoStatus
from app.security.hexstrike_operator import catalog_snapshot, operate, sync_operator_surface
from app.tools.hexstrike_defensive import HexStrikeDefensiveTool
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


def test_hexstrike_access_locked_without_license(monkeypatch):
    status = _ato(installed=False, valid=False, in_person_verified=False, modules=[])
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    monkeypatch.setattr("app.licensing.entitlements.evaluate", lambda now=None: status)
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_LOCKED
    payload = hexstrike_access_payload()
    assert payload["operator_allowed"] is False
    assert payload["blue_allowed"] is False
    assert "hexstrike" in payload["access_message"].lower() or "license" in payload["access_message"].lower()


def test_hexstrike_access_locked_without_hexstrike_module(monkeypatch):
    status = _ato(modules=["blue-team"])
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    monkeypatch.setattr("app.licensing.entitlements.evaluate", lambda now=None: status)
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_LOCKED
    payload = hexstrike_access_payload()
    assert payload["operator_allowed"] is False
    assert "hexstrike" in payload["access_message"].lower()


def test_hexstrike_access_full_when_module_present(monkeypatch):
    status = _ato(modules=["blue-team", "hexstrike"], law_enforcement=False)
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    monkeypatch.setattr("app.licensing.entitlements.evaluate", lambda now=None: status)
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_FULL
    assert hexstrike_access_payload()["operator_allowed"] is True


def test_hexstrike_access_full_for_unrestricted_package_with_modules(monkeypatch):
    status = _ato(
        package_class="owner_unrestricted",
        modules=["blue-team", "red-team", "hexstrike", "computer-use"],
        law_enforcement=True,
    )
    monkeypatch.setattr("app.policy.cyber_ato.evaluate", lambda now=None: status)
    monkeypatch.setattr("app.licensing.entitlements.evaluate", lambda now=None: status)
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_FULL


def test_status_api_locked_names_module(jarvis_env, monkeypatch, allow_loopback_api):
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


def test_operate_requires_hexstrike_module(jarvis_env, monkeypatch, allow_loopback_api):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_denied_message",
        lambda now=None: "The installed license package does not include hexstrike.",
    )
    monkeypatch.setattr(
        "app.policy.computer_permissions.evaluate_permission",
        lambda permission: SimpleNamespace(status="allow"),
    )
    client = TestClient(app)
    response = client.post(
        "/api/hexstrike/operate",
        json={"capability_id": "http:scanner_one", "arguments": {}},
    )
    assert response.status_code == 403
    assert "hexstrike" in response.json()["detail"].lower()


def test_tools_refresh_requires_hexstrike_module(jarvis_env, monkeypatch, allow_loopback_api):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_denied_message",
        lambda now=None: "The installed license package does not include hexstrike.",
    )
    client = TestClient(app)
    response = client.post("/api/hexstrike/tools/refresh")
    assert response.status_code == 403


def test_catalog_snapshot_locked_is_empty(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_denied_message",
        lambda now=None: "The installed license package does not include hexstrike.",
    )
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
    snap = catalog_snapshot()
    assert snap["access_mode"] == "locked"
    assert snap["catalog"] == []
    assert snap["discovery_ok"] is False


@pytest.mark.asyncio
async def test_sync_registers_mcp_when_full(monkeypatch):
    registered = {"called": False}

    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=".",
            python_executable="python",
            host="127.0.0.1",
            port=8888,
        )

    async def fake_register(**kwargs):
        registered["called"] = True
        return SimpleNamespace(as_dict=lambda: {"ok": True})

    async def fake_refresh(*, force=True):
        return [
            {"id": "defensive:host_baseline", "source": "defensive"},
            {"id": "http:extra", "source": "http"},
        ]

    monkeypatch.setattr("app.security.hexstrike.HEXSTRIKE.status", fake_status)
    monkeypatch.setattr("app.security.hexstrike_operator.register_hexstrike_mcp", fake_register)
    monkeypatch.setattr("app.security.hexstrike_operator.refresh_discovered_catalog", fake_refresh)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    surface = await sync_operator_surface(register_mcp=True)
    assert registered["called"] is False
    assert surface["mcp"]["ok"] is False

    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_FULL)
    surface = await sync_operator_surface(register_mcp=True)
    assert registered["called"] is True


@pytest.mark.asyncio
async def test_defensive_tool_module_message_when_locked(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_denied_message",
        lambda now=None: "The installed license package does not include hexstrike.",
    )
    tool = HexStrikeDefensiveTool(lambda: {})
    result = await tool.execute(action="host_baseline", scope_id="host")
    assert result.success is False
    assert "hexstrike" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_operator_tool_locked_names_module(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_denied_message",
        lambda now=None: "The installed license package does not include hexstrike.",
    )
    tool = HexStrikeOperatorTool(lambda: {})
    result = await tool.execute(operation="status")
    assert result.success is False
    assert "hexstrike" in (result.error or "").lower()


def test_daybreak_hud_shows_module_gating():
    source = Path("frontend/src/hud/HudHexStrikeSuite.tsx").read_text(encoding="utf-8")
    assert "Open License" in source
    assert "access_mode" in source
    assert "hexstrike" in source.lower()
    assert "Operate" in source
    assert "Jobs" in source


def test_tool_exposure_matrix(monkeypatch):
    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    mixed = tool_exposure.tool_names_for("mixed", ["hexstrike", "hexstrike_defensive"])
    assert "hexstrike_defensive" not in mixed
    assert "hexstrike_operator" not in mixed

    # Legacy blue constant no longer unlocks tools under RFC-0196.
    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_BLUE)
    blue = tool_exposure.tool_names_for("mixed", ["hexstrike", "hexstrike_defensive"])
    assert "hexstrike_defensive" not in blue
    assert "hexstrike_operator" not in blue

    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda: HEXSTRIKE_ACCESS_FULL)
    full = tool_exposure.tool_names_for("mixed", ["hexstrike", "hexstrike_defensive"])
    assert "hexstrike_defensive" in full
    assert "hexstrike_operator" in full


@pytest.mark.asyncio
async def test_operate_locked_raises_module_message(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_denied_message",
        lambda now=None: "The installed license package does not include hexstrike.",
    )
    with pytest.raises(PermissionError, match="hexstrike"):
        await operate("defensive:host_baseline", {})
