from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import repo_root
from ..hardware import hardware_dict
from .supervisor import LAUNCH_LOG_MAX_BYTES, LAUNCH_LOGS_KEPT, CoreSupervisor, rotate_file

CORE_HEALTH_URL = "http://127.0.0.1:4780/api/health"
STATIC_DIR = Path(__file__).with_name("static")
ALLOWED_ACTIONS = {"start", "stop", "restart"}


class ControlRequest(BaseModel):
    confirm: bool = False


def _root() -> Path:
    return repo_root()


async def _core_healthy() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            response = await client.get(CORE_HEALTH_URL)
            return response.is_success and bool(response.json().get("ok"))
    except Exception:
        return False


async def _core_details() -> dict:
    """Read existing core projections; manager never maintains a competing node store."""
    if not await _core_healthy():
        return {"tasks": {"active": 0, "total": 0}, "swarm": None, "model": None}
    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            system, tasks, swarm = await asyncio.gather(
                client.get("http://127.0.0.1:4780/api/system"),
                client.get("http://127.0.0.1:4780/api/tasks"),
                client.get("http://127.0.0.1:4780/api/swarm"),
            )
        task_rows = tasks.json() if tasks.is_success and isinstance(tasks.json(), list) else []
        active = sum(1 for row in task_rows if str(row.get("status", "")).lower() not in {"completed", "failed", "cancelled"})
        system_data = system.json() if system.is_success else {}
        return {
            "tasks": {"active": active, "total": len(task_rows)},
            "swarm": swarm.json() if swarm.is_success else None,
            "model": system_data.get("model"),
        }
    except Exception:
        return {"tasks": {"active": 0, "total": 0}, "swarm": None, "model": None}


def _directory_size(path: Path, *, limit: int = 10_000) -> int:
    total = 0
    try:
        for index, item in enumerate(path.rglob("*")):
            if index >= limit:
                break
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return total


def _managed_process_running() -> bool:
    # Health is the authoritative running signal; this only distinguishes a stopped
    # backend from a process that is still starting or has become unhealthy.
    try:
        import psutil

        return any(
            proc.info.get("name", "").lower().startswith(("python", "jarvis-backend"))
            and "uvicorn app.main:app" in " ".join(proc.info.get("cmdline") or [])
            for proc in psutil.process_iter(["name", "cmdline"])
        )
    except Exception:
        return False


async def status_snapshot() -> dict:
    root = _root()
    healthy = await _core_healthy()
    details = await _core_details() if healthy else {"tasks": {"active": 0, "total": 0}, "swarm": None, "model": None}
    process_present = _managed_process_running()
    state = "ready" if healthy else "starting" if process_present else "stopped"
    storage = {
        name: {"bytes": _directory_size(root / name), "exists": (root / name).exists()}
        for name in ("data", "models", "logs", "runtime")
    }
    try:
        usage = shutil.disk_usage(root)
        disk = {"free_bytes": usage.free, "total_bytes": usage.total}
    except OSError:
        disk = {"free_bytes": 0, "total_bytes": 0}
    return {
        "manager": {"healthy": True, "bind": "127.0.0.1:4782"},
        "core": {"state": state, "healthy": healthy, "process_present": process_present},
        "supervisor": SUPERVISOR.snapshot(),
        "hardware": hardware_dict(),
        "storage": {"disk": disk, "paths": storage},
        "agents": details,
    }


def _script(name: str) -> Path:
    path = _root() / name
    if not path.is_file():
        raise RuntimeError(f"Required ANZU script is missing: {path}")
    return path


def _launch(action: str) -> None:
    root = _root()
    if action == "start":
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_script("start-jarvis.ps1")), "-NoBrowser"]
    elif action == "stop":
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_root() / "installer" / "windows" / "force-stop-jarvis.ps1"), "-InstallRoot", str(root), "-PreserveManager"]
    else:
        raise RuntimeError("restart is sequenced by the control endpoint")
    # Launcher output goes to a size-rotated log so a failed start is never silent.
    log_path = root / "logs" / "anzu-launch.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rotate_file(log_path, LAUNCH_LOGS_KEPT, LAUNCH_LOG_MAX_BYTES)
    with log_path.open("ab") as handle:
        handle.write(f"\n=== {action} {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode("utf-8"))
        handle.flush()
        subprocess.Popen(
            args,
            cwd=root,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


async def _wait_for(action: str) -> dict:
    expected = action != "stop"
    for _ in range(20):
        if await _core_healthy() is expected:
            return await status_snapshot()
        await asyncio.sleep(0.5)
    return await status_snapshot()


SUPERVISOR = CoreSupervisor(
    root=lambda: _root(),
    healthy=lambda: _core_healthy(),
    process_present=lambda: _managed_process_running(),
    launch=lambda action: _launch(action),
)

# Per-manager-session token for control actions. Clients on this computer get it
# from /session (CORS limits browser readers to loopback portal origins); a page
# that cannot read it cannot start, stop or restart ANZU.
SESSION_TOKEN = secrets.token_urlsafe(32)
TOKEN_HEADER = "X-Anzu-Manager-Token"

app = FastAPI(title="ANZU Manager", docs_url=None, redoc_url=None)

# The portal (served by the core on :4780, or Vite in dev) asks the manager why
# the core is down and offers a Restart button. Only loopback portal origins may
# read or call it; the loopback_only middleware still rejects remote clients.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$",
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", TOKEN_HEADER],
)


@app.on_event("startup")
async def _start_supervisor() -> None:
    SUPERVISOR.start()


@app.on_event("shutdown")
async def _stop_supervisor() -> None:
    await SUPERVISOR.stop()


@app.middleware("http")
async def loopback_only(request: Request, call_next):
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "testclient"}:
        return JSONResponse(status_code=403, content={"detail": "ANZU Manager is available only on this computer"})
    return await call_next(request)


@app.get("/api/manager/v1/status")
async def manager_status():
    return await status_snapshot()


@app.get("/api/manager/v1/session")
async def manager_session():
    return {"token": SESSION_TOKEN, "header": TOKEN_HEADER}


@app.post("/api/manager/v1/control/{action}")
async def manager_control(
    action: Literal["start", "stop", "restart"],
    body: ControlRequest,
    token: str | None = Header(default=None, alias=TOKEN_HEADER),
):
    if not token or not secrets.compare_digest(token, SESSION_TOKEN):
        raise HTTPException(status_code=403, detail="Manager session token required")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    if SUPERVISOR.state.control_in_flight:
        raise HTTPException(status_code=409, detail=f"ANZU {SUPERVISOR.state.control_in_flight} is already in progress")
    SUPERVISOR.set_desired(action != "stop")
    async with SUPERVISOR.control_action(action):
        try:
            if action == "restart":
                _launch("stop")
                stopped = await _wait_for("stop")
                if stopped["core"]["state"] != "stopped":
                    raise HTTPException(status_code=409, detail="ANZU did not stop; restart was not attempted")
                _launch("start")
            else:
                _launch(action)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        snapshot = await _wait_for(action)
    ok = snapshot["core"]["healthy"] if action != "stop" else snapshot["core"]["state"] == "stopped"
    return {"action": action, "ok": ok, "status": snapshot}


app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/admin")
@app.get("/admin/")
async def admin_page():
    return FileResponse(STATIC_DIR / "index.html")
