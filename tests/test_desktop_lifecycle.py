from __future__ import annotations

from pathlib import Path

from app.desktop_lifecycle import (
    MAX_RESTART_ATTEMPTS,
    build_backend_launch_plan,
    health_url,
    lifecycle_status_from_flags,
    next_restart_count,
    should_restart,
)


def test_dev_launch_plan_uses_uvicorn(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    plan = build_backend_launch_plan(tmp_path)
    assert plan.mode == "python_dev"
    assert "uvicorn" in plan.args
    assert "4780" in plan.args
    assert plan.owned is True


def test_sidecar_preferred_when_present(tmp_path: Path):
    sidecar = tmp_path / "sidecars" / "jarvis-backend" / "jarvis-backend.exe"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(b"stub")
    plan = build_backend_launch_plan(tmp_path)
    assert plan.mode == "sidecar"
    assert plan.executable.endswith("jarvis-backend.exe")
    assert plan.args == []


def test_restart_bounds():
    assert should_restart(0) is True
    assert should_restart(MAX_RESTART_ATTEMPTS - 1) is True
    assert should_restart(MAX_RESTART_ATTEMPTS) is False
    assert next_restart_count(1) == 2


def test_lifecycle_status_mapping():
    assert lifecycle_status_from_flags(health_ok=True, starting=False, model_loading=False, owned_stopped=False, failed=False) == "ready"
    assert lifecycle_status_from_flags(health_ok=False, starting=True, model_loading=False, owned_stopped=False, failed=False) == "starting"
    assert lifecycle_status_from_flags(health_ok=True, starting=False, model_loading=True, owned_stopped=False, failed=False) == "model_loading"
    assert lifecycle_status_from_flags(health_ok=False, starting=False, model_loading=False, owned_stopped=False, failed=True) == "backend_failed"
    assert health_url(4780).endswith("/api/health")
