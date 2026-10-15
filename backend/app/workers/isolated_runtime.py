"""Dedicated Python environments for third-party browser/computer workers."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

IDS = frozenset({"browser-use", "ufo", "cua"})


def runtime_root(worker_id: str) -> Path:
    if worker_id not in IDS:
        raise KeyError(worker_id)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "ANZU" / "workers" / worker_id


def runtime_python(worker_id: str) -> Path:
    return runtime_root(worker_id) / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def installed_worker_python(worker_id: str) -> Path | None:
    executable = runtime_python(worker_id)
    try:
        record = json.loads((runtime_root(worker_id) / "ready.json").read_text())
    except (OSError, ValueError):
        return None
    return executable if executable.is_file() and record.get("verified") is True else None


def host_python() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    candidates = [os.environ.get("JARVIS_WORKER_PYTHON", ""), shutil.which("python") or ""]
    for candidate in candidates:
        if not candidate or Path(candidate).resolve() == Path(sys.executable).resolve():
            continue
        try:
            result = subprocess.run([candidate, "-c", "import sys; print(sys.version_info >= (3, 11))"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip() == "True":
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise RuntimeError("Optional workers require a real Python 3.11+ runtime. Install Python or set JARVIS_WORKER_PYTHON; the ANZU executable cannot run pip.")


async def run_isolated(worker_id: str, payload: dict, *, timeout: int = 180, executable_override: str | None = None):
    from ..tools.base import ToolResult
    from ..tools.owner_paths import direct_child_env

    executable = executable_override or installed_worker_python(worker_id)
    if executable is None:
        return ToolResult(False, "", error=f"{worker_id} is not installed in its dedicated environment. Use Install now on Tools.")
    entry = Path(__file__).with_name("isolated_entry.py")
    env = direct_child_env()
    env.update(ANONYMIZED_TELEMETRY="false", BROWSER_USE_LOGGING_LEVEL="error", DO_NOT_TRACK="1")
    process = await asyncio.create_subprocess_exec(str(executable), str(entry), worker_id, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    try:
        output, errors = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if os.name == "nt":
            cleanup = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await cleanup.wait()
        elif process.returncode is None:
            process.kill()
        await process.wait()
        raise
    try:
        reply = json.loads(output.decode("utf-8"))
    except (ValueError, UnicodeError):
        return ToolResult(False, "", error=f"{worker_id} returned no valid result (exit {process.returncode}). See the worker environment for import/runtime diagnostics.")
    return ToolResult(bool(reply.get("success")) and process.returncode == 0, str(reply.get("output") or ""), data=reply.get("data") or {}, error=str(reply.get("error") or ""))
