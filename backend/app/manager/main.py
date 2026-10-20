from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import repo_root
from ..hardware import hardware_dict
from . import debug_log
from .redact import redact_headers, register_secret
from .supervisor import LAUNCH_LOG_MAX_BYTES, LAUNCH_LOGS_KEPT, CoreSupervisor, rotate_file

# RFC-0229 S1: app.js is an ES module, and browsers/WebView2 refuse a module served
# as anything but JavaScript. Starlette's StaticFiles takes Content-Type from
# Python mimetypes, which on Windows reads the registry (often .js -> text/plain),
# so pin it before the /assets mount below.
mimetypes.add_type("text/javascript", ".js")

CORE_HEALTH_URL = "http://127.0.0.1:4780/api/health"
STATIC_DIR = Path(__file__).with_name("static")
ALLOWED_ACTIONS = {"start", "stop", "restart"}


class ControlRequest(BaseModel):
    confirm: bool = False


class VerboseRequest(BaseModel):
    enabled: bool


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
    except Exception as exc:
        debug_log.write("WARNING", "status_error", detail={"error": f"core details unavailable: {exc}"})
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


# force-stop-jarvis.ps1 can take ~1 min (polite stop, then lockers, then port recheck).
STOP_SCRIPT_TIMEOUT_SECONDS = 150.0
START_HEALTH_WAIT_SECONDS = 90.0
STOP_HEALTH_WAIT_SECONDS = 10.0


def _launch(action: str) -> None:
    """Start or stop the core. ``stop`` blocks until the stop script has exited.

    force-stop kills every Jarvis process under the install root, so a start
    launched while it is still running gets killed as a "locker"; the restart
    and watchdog paths therefore must not start until stop has fully finished.
    """
    root = _root()
    if action == "start":
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_script("start-jarvis.ps1")), "-NoBrowser"]
    elif action == "stop":
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_root() / "installer" / "windows" / "force-stop-jarvis.ps1"), "-InstallRoot", str(root), "-PreserveManager"]
    else:
        raise RuntimeError("restart is sequenced by the control endpoint")
    # Launcher output goes to a size-rotated log so a failed start is never silent.
    debug_log.spawn(action, args, os.environ)
    log_path = root / "logs" / "anzu-launch.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rotate_file(log_path, LAUNCH_LOGS_KEPT, LAUNCH_LOG_MAX_BYTES)
    with log_path.open("ab") as handle:
        handle.write(f"\n=== {action} {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode("utf-8"))
        handle.flush()
        proc = subprocess.Popen(
            args,
            cwd=root,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if action == "stop":
        try:
            code = proc.wait(timeout=STOP_SCRIPT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            _kill_process_tree(proc)
            log.error("ANZU stop script exceeded %ss; killed its process tree", int(STOP_SCRIPT_TIMEOUT_SECONDS))
            raise RuntimeError(
                f"ANZU stop did not finish within {int(STOP_SCRIPT_TIMEOUT_SECONDS)}s; start was not attempted"
            ) from exc
        if code != 0:
            log.error("ANZU stop script failed with exit code %s", code)
            raise RuntimeError(f"ANZU stop failed (exit code {code}); start was not attempted")


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a timed-out stop script and its children, then reap it."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            proc.kill()
    except Exception:
        log.warning("Could not kill stop-script tree %s", proc.pid, exc_info=True)
    try:
        proc.wait(timeout=30)
    except Exception:
        log.warning("Stop script %s still running after kill", proc.pid, exc_info=True)


async def _wait_for(action: str) -> dict:
    expected = action != "stop"
    seconds = STOP_HEALTH_WAIT_SECONDS if action == "stop" else START_HEALTH_WAIT_SECONDS
    for _ in range(int(seconds / 0.5)):
        if await _core_healthy() is expected:
            return await status_snapshot()
        await asyncio.sleep(0.5)
    return await status_snapshot()


log = logging.getLogger(__name__)

debug_log.configure(lambda: _root())

SUPERVISOR = CoreSupervisor(
    root=lambda: _root(),
    healthy=lambda: _core_healthy(),
    process_present=lambda: _managed_process_running(),
    launch=lambda action: _launch(action),
    on_event=lambda level, action, detail: debug_log.write(level, "supervisor", action=action, detail=detail),
)

# Per-manager-session token for control actions. Clients on this computer get it
# from /session (CORS limits browser readers to loopback portal origins); a page
# that cannot read it cannot start, stop or restart ANZU.
SESSION_TOKEN = secrets.token_urlsafe(32)
TOKEN_HEADER = "X-Anzu-Manager-Token"
register_secret(SESSION_TOKEN)  # never written to the debug log or returned by it

# RFC-0229 S1: every control press carries a client request id (logged at receipt
# and completion) and reports its phase while it runs.
REQUEST_ID_HEADER = "X-Anzu-Request-Id"
# Only the Manager page itself may switch verbose logging on (not the :4780 portal).
MANAGER_ORIGINS = frozenset({"http://127.0.0.1:4782", "http://localhost:4782"})
PHASE_TEXT = {
    "stopping": "Stopping…",
    "waiting_stop": "Waiting for ANZU to stop…",
    "starting": "Starting…",
    "waiting_health": "Waiting for health…",
}
_clock = time.monotonic
CONTROL_PROGRESS: dict = {}


def _set_phase(phase: str) -> None:
    CONTROL_PROGRESS["phase"] = phase
    CONTROL_PROGRESS["phase_text"] = PHASE_TEXT[phase]
    debug_log.write(
        "DEBUG",
        "control_start",
        action=CONTROL_PROGRESS.get("action"),
        request_id=CONTROL_PROGRESS.get("request_id"),
        detail={"phase": phase},
    )


def control_progress() -> dict:
    if not CONTROL_PROGRESS:
        return {"active": False}
    return {
        "active": True,
        "action": CONTROL_PROGRESS["action"],
        "request_id": CONTROL_PROGRESS["request_id"],
        "phase": CONTROL_PROGRESS.get("phase"),
        "phase_text": CONTROL_PROGRESS.get("phase_text"),
        "elapsed_ms": round((_clock() - CONTROL_PROGRESS["started"]) * 1000),
    }


def _token_ok(token: str | None) -> bool:
    return bool(token) and secrets.compare_digest(token, SESSION_TOKEN)

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


@app.get("/api/manager/v1/control/progress")
async def manager_control_progress():
    return control_progress()


@app.post("/api/manager/v1/control/{action}")
async def manager_control(
    action: Literal["start", "stop", "restart"],
    body: ControlRequest,
    request: Request,
    token: str | None = Header(default=None, alias=TOKEN_HEADER),
    client_request_id: str | None = Header(default=None, alias=REQUEST_ID_HEADER),
):
    request_id = debug_log.clean_request_id(client_request_id)
    started = _clock()
    debug_log.write("INFO", "press", action=action, request_id=request_id)
    debug_log.write("DEBUG", "press", action=action, request_id=request_id, detail={"headers": redact_headers(request.headers)})
    ok = False
    error: str | None = None
    try:
        result = await _run_control(action, body, token, request_id)
        ok = bool(result["ok"])
        return result
    except HTTPException as exc:
        error = f"{exc.status_code}: {exc.detail}"
        raise
    finally:
        debug_log.write(
            "INFO" if ok else "WARNING",
            "control_end",
            action=action,
            request_id=request_id,
            duration_ms=round((_clock() - started) * 1000),
            ok=ok,
            detail={"error": error} if error else None,
        )


async def _run_control(action: str, body: ControlRequest, token: str | None, request_id: str) -> dict:
    if not _token_ok(token):
        raise HTTPException(status_code=403, detail="Manager session token required")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    if SUPERVISOR.state.control_in_flight:
        raise HTTPException(status_code=409, detail=f"ANZU {SUPERVISOR.state.control_in_flight} is already in progress")
    SUPERVISOR.set_desired(action != "stop")
    debug_log.write("INFO", "control_start", action=action, request_id=request_id)
    bound = debug_log.bind_control(action, request_id)
    CONTROL_PROGRESS.clear()
    CONTROL_PROGRESS.update({"action": action, "request_id": request_id, "started": _clock()})
    try:
        async with SUPERVISOR.control_action(action):
            try:
                if action == "restart":
                    _set_phase("stopping")
                    await asyncio.to_thread(_launch, "stop")
                    _set_phase("waiting_stop")
                    stopped = await _wait_for("stop")
                    if stopped["core"]["state"] != "stopped":
                        raise HTTPException(status_code=409, detail="ANZU did not stop; restart was not attempted")
                    _set_phase("starting")
                    await asyncio.to_thread(_launch, "start")
                    SUPERVISOR.note_launch()
                else:
                    _set_phase("stopping" if action == "stop" else "starting")
                    await asyncio.to_thread(_launch, action)
                    if action == "start":
                        SUPERVISOR.note_launch()
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            _set_phase("waiting_stop" if action == "stop" else "waiting_health")
            snapshot = await _wait_for(action)
    finally:
        CONTROL_PROGRESS.clear()
        debug_log.unbind_control(bound)
    ok = snapshot["core"]["healthy"] if action != "stop" else snapshot["core"]["state"] == "stopped"
    return {"action": action, "ok": ok, "status": snapshot}


@app.get("/api/manager/v1/debug-log")
async def manager_debug_log(tail: int = Query(default=200, ge=1, le=2000)):
    lines = await asyncio.to_thread(debug_log.read_tail, tail)
    return {"lines": lines, "verbose": debug_log.is_verbose()}


@app.post("/api/manager/v1/debug-log/verbose")
async def manager_debug_log_verbose(
    body: VerboseRequest,
    token: str | None = Header(default=None, alias=TOKEN_HEADER),
    origin: str | None = Header(default=None),
):
    # Loopback middleware already ran; additionally require the session token and
    # the Manager page's own origin, so the :4780 portal (which can read /session)
    # still cannot switch verbose on.
    if not _token_ok(token):
        raise HTTPException(status_code=403, detail="Manager session token required")
    if origin not in MANAGER_ORIGINS:
        raise HTTPException(status_code=403, detail="Verbose logging can be changed only from the ANZU Manager page")
    debug_log.set_verbose(body.enabled)
    return {"verbose": debug_log.is_verbose()}


app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/admin")
@app.get("/admin/")
async def admin_page():
    return FileResponse(STATIC_DIR / "index.html")
