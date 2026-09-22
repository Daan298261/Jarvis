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
    HEXSTRIKE_PRO_MESSAGE,
    hexstrike_access_mode,
    hexstrike_access_payload,
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
    )
    values.update(overrides)
    return AtoStatus(**values)  # type: ignore[arg-type]


def test_hexstrike_access_locked_without_license(monkeypatch):
    monkeypatch.setattr(
        "app.licensing.entitlements.evaluate",
        lambda now=None: _ato(installed=False, valid=False, in_person_verified=False),
    )
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_LOCKED
    payload = hexstrike_access_payload()
    assert payload["operator_allowed"] is False
    assert payload["blue_allowed"] is False
    assert "Pro feature" in payload["access_message"]


def test_hexstrike_access_blue_for_ordinary_license(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.evaluate", lambda now=None: _ato())
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_BLUE
    payload = hexstrike_access_payload()
    assert payload["blue_allowed"] is True
    assert payload["operator_allowed"] is False
    assert "unrestricted or law-enforcement" in payload["access_message"]


def test_hexstrike_access_full_for_law_enforcement(monkeypatch):
    monkeypatch.setattr(
        "app.licensing.entitlements.evaluate",
        lambda now=None: _ato(law_enforcement=True, red_team=True),
    )
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_FULL
    assert hexstrike_access_payload()["operator_allowed"] is True


def test_hexstrike_access_full_for_unrestricted_package(monkeypatch):
    monkeypatch.setattr(
        "app.licensing.entitlements.evaluate",
        lambda now=None: _ato(package_class="owner_unrestricted"),
    )
    assert hexstrike_access_mode() == HEXSTRIKE_ACCESS_FULL


def test_status_api_locked_is_pro_message_without_catalog(jarvis_env, monkeypatch, allow_loopback_api):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    monkeypatch.setattr(
        "app.licensing.entitlements.hexstrike_access_payload",
        lambda now=None: {
            "access_mode": "locked",
            "access_message": HEXSTRIKE_PRO_MESSAGE,
            "operator_allowed": False,
            "blue_allowed": False,
        },
    )
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.resolve_install", lambda explicit="": None)
    client = TestClient(app)
    body = client.get("/api/hexstrike").json()
    assert body["access_mode"] == "locked"
    assert body["catalog"] == []
    assert "Pro feature" in body["access_message"]
    start = client.post("/api/hexstrike/start")
    assert start.status_code == 403
    assert "Pro feature" in start.json()["detail"]


def test_operate_http_capability_requires_full_license(jarvis_env, monkeypatch, allow_loopback_api):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_BLUE)
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
    assert "unrestricted or law-enforcement" in response.json()["detail"]


def test_tools_refresh_requires_full_license(jarvis_env, monkeypatch, allow_loopback_api):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_BLUE)
    client = TestClient(app)
    response = client.post("/api/hexstrike/tools/refresh")
    assert response.status_code == 403


def test_catalog_snapshot_blue_keeps_only_defensive(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_BLUE)
    snap = catalog_snapshot()
    assert snap["access_mode"] == "blue"
    assert all(row.get("source") == "defensive" for row in snap["catalog"])
    assert snap["count"] >= 1


@pytest.mark.asyncio
async def test_sync_skips_mcp_unless_full(monkeypatch):
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
        return [{"id": "defensive:host_baseline", "source": "defensive"}]

    monkeypatch.setattr("app.security.hexstrike.HEXSTRIKE.status", fake_status)
    monkeypatch.setattr("app.security.hexstrike_operator.register_hexstrike_mcp", fake_register)
    monkeypatch.setattr("app.security.hexstrike_operator.refresh_discovered_catalog", fake_refresh)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_BLUE)
    surface = await sync_operator_surface(register_mcp=True)
    assert registered["called"] is False
    assert surface["mcp"]["ok"] is False

    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_FULL)
    surface = await sync_operator_surface(register_mcp=True)
    assert registered["called"] is True


@pytest.mark.asyncio
async def test_defensive_tool_pro_message_when_locked(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    tool = HexStrikeDefensiveTool(lambda: {})
    result = await tool.execute(action="host_baseline", scope_id="host")
    assert result.success is False
    assert result.error == HEXSTRIKE_PRO_MESSAGE


@pytest.mark.asyncio
async def test_operator_tool_blue_license_message(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_BLUE)
    tool = HexStrikeOperatorTool(lambda: {})
    result = await tool.execute(operation="status")
    assert result.success is False
    assert result.error == HEXSTRIKE_OPERATOR_LICENSE_MESSAGE


def test_daybreak_hud_shows_pro_copy_and_license_gating():
    source = Path("frontend/src/hud/HudHexStrikeSuite.tsx").read_text(encoding="utf-8")
    assert "Pro feature" in source
    assert "HexStrike Blue · defensive suite" in source
    assert "Open License" in source
    assert "access_mode" in source


def test_tool_exposure_matrix(monkeypatch):
    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    mixed = tool_exposure.tool_names_for("mixed", ["hexstrike", "hexstrike_defensive"])
    assert "hexstrike_defensive" not in mixed
    assert "hexstrike_operator" not in mixed

    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_BLUE)
    blue = tool_exposure.tool_names_for("mixed", ["hexstrike", "hexstrike_defensive"])
    assert "hexstrike_defensive" in blue
    assert "hexstrike_operator" not in blue

    monkeypatch.setattr(tool_exposure, "hexstrike_access_mode", lambda: HEXSTRIKE_ACCESS_FULL)
    full = tool_exposure.tool_names_for("mixed", ["hexstrike", "hexstrike_defensive"])
    assert "hexstrike_defensive" in full
    assert "hexstrike_operator" in full


@pytest.mark.asyncio
async def test_operate_locked_raises_pro(monkeypatch):
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: HEXSTRIKE_ACCESS_LOCKED)
    with pytest.raises(PermissionError, match="Pro feature"):
        await operate("defensive:host_baseline", {})
