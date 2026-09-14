"""Start a local LM Studio app + HTTP server when Play needs it."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .backends import probe_remote_server

_log = logging.getLogger(__name__)

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SERVER_WAIT_SECONDS = 45.0
POLL_SECONDS = 1.0


def is_loopback_host(host: str) -> bool:
    return (host or "").strip().lower() in LOOPBACK


def lmstudio_cli() -> str | None:
    found = shutil.which("lms")
    if found:
        return found
    home = Path.home()
    for candidate in (home / ".lmstudio" / "bin" / "lms.exe", home / ".lmstudio" / "bin" / "lms"):
        if candidate.is_file():
            return str(candidate)
    return None


def lmstudio_app_path() -> Path | None:
    local = Path(os.environ.get("LOCALAPPDATA") or "")
    program_files = Path(os.environ.get("PROGRAMFILES") or r"C:\Program Files")
    candidates = (
        local / "Programs" / "LM Studio" / "LM Studio.exe",
        local / "LM-Studio" / "LM Studio.exe",
        program_files / "LM Studio" / "LM Studio.exe",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _launch_app(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 — owner-local LM Studio executable
        return
    subprocess.Popen(  # noqa: S603
        [str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _run_cli(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


async def _wait_until_up(host: str, port: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {"ok": False, "error": "LM Studio did not become ready"}
    while time.monotonic() < deadline:
        last = await probe_remote_server(host, port, timeout=2.0, retry=False)
        if last.get("ok"):
            return last
        await asyncio.sleep(POLL_SECONDS)
    return last


async def ensure_local_lmstudio(
    *,
    host: str,
    port: int,
    model: str = "",
    timeout: float = SERVER_WAIT_SECONDS,
) -> dict[str, Any]:
    """Bring up loopback LM Studio so Play can continue without a manual start."""
    if not is_loopback_host(host):
        return {"ok": False, "method": "skipped", "detail": "refusing to auto-start a remote LM Studio"}

    probe = await probe_remote_server(host, port, timeout=2.0, retry=False)
    if probe.get("ok"):
        return {"ok": True, "method": "already-up", "detail": "LM Studio was already serving"}

    cli = lmstudio_cli()
    app = lmstudio_app_path()
    if not cli and not app:
        return {
            "ok": False,
            "method": "missing",
            "detail": "LM Studio is not installed on this PC",
        }

    if app:
        try:
            await asyncio.to_thread(_launch_app, app)
        except Exception as exc:
            _log.warning("Could not launch LM Studio app: %s", exc)

    if cli:
        try:
            started = await asyncio.to_thread(
                _run_cli,
                [cli, "server", "start"] if int(port) == 1234 else [cli, "server", "start", "--port", str(int(port))],
                30.0,
            )
            if started.returncode != 0:
                _log.warning(
                    "lms server start exited %s: %s",
                    started.returncode,
                    (started.stderr or started.stdout or "")[:400],
                )
        except Exception as exc:
            _log.warning("lms server start failed: %s", exc)

    ready = await _wait_until_up(host, port, timeout)
    if not ready.get("ok"):
        return {
            "ok": False,
            "method": "wait",
            "detail": ready.get("error") or "LM Studio did not open its local server",
        }

    hint = (model or "").strip()
    if hint and cli:
        try:
            loaded = await asyncio.to_thread(_run_cli, [cli, "load", hint, "-y"], min(timeout, 90.0))
            if loaded.returncode != 0:
                _log.warning("lms load failed: %s", (loaded.stderr or loaded.stdout or "")[:400])
        except Exception as exc:
            _log.warning("lms load failed: %s", exc)
        ready = await probe_remote_server(host, port, timeout=4.0, retry=True)

    return {
        "ok": bool(ready.get("ok")),
        "method": "auto-start",
        "detail": "Started LM Studio on this PC",
        "models": list(ready.get("models") or []),
    }
