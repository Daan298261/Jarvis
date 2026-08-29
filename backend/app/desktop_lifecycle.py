"""Backend lifecycle helpers shared conceptually with the Tauri shell.

Pure Python so Linux CI can unit-test command construction and restart bounds
without Windows or a real Tauri runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_API_PORT = 4780
MAX_RESTART_ATTEMPTS = 3
HEALTH_TIMEOUT_SECONDS = 90


@dataclass
class BackendLaunchPlan:
    executable: str
    args: list[str]
    cwd: str
    owned: bool
    mode: str  # sidecar | python_dev


def build_backend_launch_plan(root: Path, *, port: int = DEFAULT_API_PORT) -> BackendLaunchPlan:
    root = Path(root)
    sidecar_candidates = [
        root / "sidecars" / "jarvis-backend" / "jarvis-backend.exe",
        root / "sidecars" / "jarvis-backend.exe",
        root / "runtime" / "backend" / "jarvis-backend" / "jarvis-backend.exe",
        root / "frontend" / "src-tauri" / "sidecars" / "jarvis-backend" / "jarvis-backend.exe",
    ]
    for candidate in sidecar_candidates:
        if candidate.exists():
            return BackendLaunchPlan(
                executable=str(candidate),
                args=[],
                cwd=str(root),
                owned=True,
                mode="sidecar",
            )

    venv_py = root / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        venv_py = root / ".venv" / "bin" / "python"
    python = str(venv_py if venv_py.exists() else "python3")
    args = [
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--app-dir",
        str(root / "backend"),
    ]
    return BackendLaunchPlan(
        executable=python,
        args=args,
        cwd=str(root),
        owned=True,
        mode="python_dev",
    )


def should_restart(restart_count: int, *, max_attempts: int = MAX_RESTART_ATTEMPTS) -> bool:
    return int(restart_count) < int(max_attempts)


def next_restart_count(restart_count: int) -> int:
    return int(restart_count) + 1


def health_url(port: int = DEFAULT_API_PORT) -> str:
    return f"http://127.0.0.1:{int(port)}/api/health"


def lifecycle_status_from_flags(
    *,
    health_ok: bool,
    starting: bool,
    model_loading: bool,
    owned_stopped: bool,
    failed: bool,
) -> str:
    if failed:
        return "backend_failed"
    if owned_stopped:
        return "backend_stopped"
    if starting and not health_ok:
        return "starting"
    if health_ok and model_loading:
        return "model_loading"
    if health_ok:
        return "ready"
    if starting:
        return "starting"
    return "degraded"


def plan_as_dict(plan: BackendLaunchPlan) -> dict[str, Any]:
    return {
        "executable": plan.executable,
        "args": list(plan.args),
        "cwd": plan.cwd,
        "owned": plan.owned,
        "mode": plan.mode,
    }
