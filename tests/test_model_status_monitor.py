"""Model/runtime status cache + background monitor (Wave B quality ticket)."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.config import AppSettings
from app.inference.status_monitor import ModelStatusMonitor, STATUS_MONITOR


@pytest.fixture
def settings():
    return AppSettings(inference={"backend": "remote", "host": "127.0.0.1", "port": 18088})


@pytest.fixture
def monitor():
    m = ModelStatusMonitor(
        fresh_ttl_seconds=2.0,
        stale_ttl_seconds=15.0,
        hard_ttl_seconds=60.0,
        poll_interval_seconds=30.0,
    )
    yield m
    m.reset_for_tests()


async def test_cache_hit_avoids_reprobe(monitor, settings, monkeypatch):
    calls = {"n": 0}

    async def fake_live(settings_arg):
        calls["n"] += 1
        return {
            "loaded": True,
            "loading": False,
            "healthy": True,
            "host": settings_arg.inference.host,
            "port": settings_arg.inference.port,
            "last_error": "",
        }

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", fake_live)
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": True, "loading": False, "last_error": ""},
    )

    first = await monitor.get_snapshot(settings)
    second = await monitor.get_snapshot(settings)

    assert calls["n"] == 1
    assert first["status_cache"]["status"] == "fresh"
    assert second["status_cache"]["status"] == "fresh"
    assert first["healthy"] is True
    assert second["healthy"] is True
    assert "load_progress_percent" not in second
    assert "loading_percent" not in second


async def test_stale_serves_cache_and_schedules_refresh(monitor, settings, monkeypatch):
    calls = {"n": 0}

    async def fake_live(settings_arg):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return {"loaded": True, "loading": False, "healthy": True, "last_error": ""}

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", fake_live)
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": True, "loading": False, "last_error": ""},
    )

    monitor.fresh_ttl_seconds = 0.05
    monitor.stale_ttl_seconds = 5.0
    await monitor.get_snapshot(settings)
    assert calls["n"] == 1

    await asyncio.sleep(0.08)
    stale = await monitor.get_snapshot(settings)
    assert stale["status_cache"]["status"] == "stale"
    assert stale["status_cache"]["stale"] is True
    assert stale["healthy"] is True
    # Background refresh scheduled; request path did not await a second probe yet.
    assert calls["n"] == 1

    await asyncio.sleep(0.12)
    assert calls["n"] == 2


async def test_miss_beyond_hard_ttl_awaits_refresh(monitor, settings, monkeypatch):
    calls = {"n": 0}

    async def fake_live(settings_arg):
        calls["n"] += 1
        return {"loaded": False, "loading": False, "healthy": False, "last_error": ""}

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", fake_live)
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": False, "loading": False, "last_error": ""},
    )

    await monitor.get_snapshot(settings)
    assert calls["n"] == 1

    monitor.fresh_ttl_seconds = 0.01
    monitor.stale_ttl_seconds = 0.02
    monitor.hard_ttl_seconds = 0.03
    assert monitor._entry is not None
    monitor._entry.probed_at_mono = time.monotonic() - 1.0

    await monitor.get_snapshot(settings)
    assert calls["n"] == 2


async def test_probe_failure_does_not_soft_pass_healthy(monitor, settings, monkeypatch):
    async def boom(settings_arg):
        raise RuntimeError("engine unreachable")

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", boom)
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.unprobed_snapshot",
        lambda s: {
            "loaded": False,
            "loading": False,
            "healthy": True,  # even if a buggy helper lied, monitor must force False
            "last_error": "",
        },
    )
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": False, "loading": False, "last_error": ""},
    )

    snap = await monitor.get_snapshot(settings)
    assert snap["healthy"] is False
    assert snap["status_cache"]["probe_ok"] is False
    assert snap["status_cache"]["status"] in {"miss", "error"}
    assert "engine unreachable" in (snap.get("last_error") or snap["status_cache"]["last_probe_error"])


async def test_failed_refresh_after_success_clears_healthy(monitor, settings, monkeypatch):
    state = {"ok": True}

    async def flaky(settings_arg):
        if state["ok"]:
            return {"loaded": True, "loading": False, "healthy": True, "last_error": ""}
        raise RuntimeError("probe collapsed")

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", flaky)
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": True, "loading": False, "last_error": ""},
    )

    good = await monitor.refresh(settings)
    assert good["healthy"] is True
    assert good["status_cache"]["probe_ok"] is True

    state["ok"] = False
    bad = await monitor.refresh(settings)
    assert bad["healthy"] is False
    assert bad["status_cache"]["probe_ok"] is False
    assert bad["status_cache"]["status"] == "error"


async def test_never_probed_fail_closed_via_manager_snapshot(settings, monkeypatch):
    STATUS_MONITOR.reset_for_tests()

    async def boom(settings_arg):
        raise RuntimeError("no runtime")

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", boom)
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.unprobed_snapshot",
        lambda s: {"loaded": False, "loading": False, "healthy": False, "last_error": ""},
    )
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": False, "loading": False, "last_error": ""},
    )

    from app.inference.manager import MANAGER

    snap = await MANAGER.snapshot(settings)
    assert snap["healthy"] is False
    assert snap["status_cache"]["probe_ok"] is False


async def test_live_snapshot_bypasses_cache(settings, monkeypatch):
    STATUS_MONITOR.reset_for_tests()
    calls = {"n": 0}

    async def fake_live(settings_arg):
        calls["n"] += 1
        return {"loaded": False, "loading": False, "healthy": False}

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", fake_live)

    from app.inference.manager import MANAGER

    # Seed cache through monitor path once.
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": False, "loading": False, "last_error": ""},
    )
    await MANAGER.snapshot(settings)
    assert calls["n"] == 1
    await MANAGER.snapshot(settings)
    assert calls["n"] == 1
    await MANAGER.snapshot(settings, live=True)
    assert calls["n"] == 2


async def test_overlay_loading_without_inventing_progress(monitor, settings, monkeypatch):
    async def fake_live(settings_arg):
        return {"loaded": False, "loading": False, "healthy": False, "last_error": ""}

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", fake_live)
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": False, "loading": True, "last_error": ""},
    )

    snap = await monitor.get_snapshot(settings)
    assert snap["loading"] is True
    assert snap.get("load_progress_percent") is None
    assert snap.get("progress_percent") is None


async def test_background_monitor_refreshes(monitor, settings, monkeypatch):
    calls = {"n": 0}

    async def fake_live(settings_arg):
        calls["n"] += 1
        return {"loaded": False, "loading": False, "healthy": False, "last_error": ""}

    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", fake_live)
    monkeypatch.setattr(
        "app.inference.manager.MANAGER.live_state_overlay",
        lambda: {"loaded": False, "loading": False, "last_error": ""},
    )
    monkeypatch.setattr("app.inference.status_monitor.load_settings", lambda: settings)

    monitor.poll_interval_seconds = 0.05
    monitor.start()
    try:
        await asyncio.sleep(0.18)
        assert calls["n"] >= 2
        assert monitor._entry is not None
        assert monitor._entry.probe_ok is True
    finally:
        monitor.stop()
