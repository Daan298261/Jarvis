"""Elevation degrade / startup plan — no UAC automation."""

from __future__ import annotations

import logging

import pytest

from app.runtime import elevation as elev
from app.runtime.elevation import (
    LIMITED_WITHOUT_ELEVATION,
    elevation_startup_plan,
    log_elevation_startup_status,
)


def test_elevation_startup_plan_elevated_continues():
    plan = elevation_startup_plan(
        elevated=True,
        logon_task_registered=True,
        platform="nt",
    )
    assert plan["action"] == "continue"
    assert plan["run_mode"] == "elevated"
    assert plan["elevation_degraded"] is False
    assert plan["limited_features"] == []


def test_elevation_startup_plan_denied_continues_degraded():
    plan = elevation_startup_plan(
        elevated=False,
        logon_task_registered=False,
        platform="nt",
    )
    assert plan["action"] == "continue_degraded"
    assert plan["run_mode"] == "standard"
    assert plan["elevation_degraded"] is True
    assert plan["limited_features"] == list(LIMITED_WITHOUT_ELEVATION)
    assert "kill_protected_processes" in plan["detail"]


def test_elevation_startup_plan_prefers_logon_task_relaunch():
    plan = elevation_startup_plan(
        elevated=False,
        logon_task_registered=True,
        platform="nt",
    )
    assert plan["action"] == "relaunch_via_logon_task"
    assert plan["run_mode"] == "pending_task_elevate"
    assert plan["elevation_degraded"] is True
    assert "schtasks" in plan["detail"].lower() or "logon task" in plan["detail"].lower()


def test_snapshot_marks_non_elevated_as_degraded(monkeypatch):
    elev.invalidate_logon_task_cache()
    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "is_elevated", lambda: False)
    monkeypatch.setattr(elev, "logon_task_registered", lambda **_k: False)
    snap = elev.snapshot()
    assert snap["elevated"] is False
    assert snap["elevation_degraded"] is True
    assert snap["run_mode"] == "standard"
    assert snap["startup_action"] == "continue_degraded"
    assert "kill_protected_processes" in snap["limited_features"]
    assert snap["needs_uac"] is True


def test_snapshot_elevated_full_control(monkeypatch):
    elev.invalidate_logon_task_cache()
    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "is_elevated", lambda: True)
    monkeypatch.setattr(elev, "logon_task_registered", lambda **_k: True)
    snap = elev.snapshot()
    assert snap["elevated"] is True
    assert snap["elevation_degraded"] is False
    assert snap["run_mode"] == "elevated"
    assert snap["limited_features"] == []
    assert snap["needs_uac"] is False


def test_snapshot_task_registered_pending_elevate(monkeypatch):
    elev.invalidate_logon_task_cache()
    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "is_elevated", lambda: False)
    monkeypatch.setattr(elev, "logon_task_registered", lambda **_k: True)
    snap = elev.snapshot()
    assert snap["startup_action"] == "relaunch_via_logon_task"
    assert snap["elevation_degraded"] is True
    assert snap["logon_task_registered"] is True


def test_log_elevation_startup_status_warns_when_degraded(monkeypatch, caplog):
    elev.invalidate_logon_task_cache()
    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "is_elevated", lambda: False)
    monkeypatch.setattr(elev, "logon_task_registered", lambda **_k: False)
    with caplog.at_level(logging.WARNING, logger="jarvis.elevation"):
        snap = log_elevation_startup_status()
    assert snap["elevation_degraded"] is True
    assert any("Elevation degraded" in rec.message for rec in caplog.records)
    assert any("kill_protected_processes" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_api_health_includes_elevation_degrade_fields(monkeypatch):
    from app.main import health

    elev.invalidate_logon_task_cache()
    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "is_elevated", lambda: False)
    monkeypatch.setattr(elev, "_query_logon_task_registered", lambda: False)
    monkeypatch.setattr(elev, "_LOGON_TASK_CACHE_TTL_S", 60.0)

    payload = await health()
    assert payload["ok"] is True
    assert payload["elevation_degraded"] is True
    assert payload["run_mode"] == "standard"
    assert "kill_protected_processes" in payload["limited_features"]
