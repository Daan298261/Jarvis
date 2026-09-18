"""RFC-0124: Detached launch of clean-reinstall-jarvis.ps1 (portal / recovery CTA)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..config import repo_root
from .confirm_token import verify_confirm_token
from .owned_paths import log_paths_for_install, owned_paths_preview

LOG = logging.getLogger(__name__)

DURABLE_STATUS_BASENAME = "Jarvis-clean-reinstall.status.json"
DURABLE_LOG_BASENAME = "Jarvis-clean-reinstall.log"


def clean_reinstall_script_path() -> Path:
    return repo_root() / "installer" / "windows" / "clean-reinstall-jarvis.ps1"


def force_stop_script_path() -> Path:
    return repo_root() / "installer" / "windows" / "force-stop-jarvis.ps1"


def _temp_dir() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")


def durable_status_path() -> Path:
    return _temp_dir() / DURABLE_STATUS_BASENAME


def durable_log_path() -> Path:
    return _temp_dir() / DURABLE_LOG_BASENAME


def write_status_file(*, status: str, exit_reason: str | None = None) -> None:
    payload = {
        "status": status,
        "exit_reason": exit_reason or "",
        "log_path": str(durable_log_path()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        durable_status_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        LOG.warning("could not write clean reinstall status file", exc_info=True)


def read_clean_reinstall_status() -> dict[str, Any]:
    logs = log_paths_for_install()
    status_path = durable_status_path()
    log_path = durable_log_path()
    if not status_path.is_file():
        return {
            "status": "idle",
            "exit_reason": None,
            "log_paths": logs,
            "log_tail": _read_log_tail(log_path),
            "updated_at": None,
            "note": "No helper run recorded yet, or status file was removed.",
        }

    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "unknown",
            "exit_reason": None,
            "log_paths": logs,
            "log_tail": _read_log_tail(log_path),
            "updated_at": None,
            "note": "Status file exists but could not be parsed.",
        }

    raw_status = str(data.get("status") or "unknown")
    exit_reason = str(data.get("exit_reason") or "") or None
    mapped = raw_status
    if raw_status == "running":
        mapped = "running"
    elif raw_status in {"succeeded", "ok"} or exit_reason == "ok":
        mapped = "succeeded"
    elif raw_status in {"failed", "aborted"} or exit_reason:
        mapped = "failed"

    return {
        "status": mapped,
        "exit_reason": exit_reason,
        "log_paths": logs,
        "log_tail": _read_log_tail(log_path),
        "updated_at": data.get("updated_at"),
        "note": None,
    }


def _read_log_tail(log_path: Path, max_lines: int = 24) -> list[str]:
    if not log_path.is_file():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max_lines:]


def start_clean_reinstall_detached(
    *,
    confirm_token: str,
    acknowledged_roots: list[str],
    final_confirm: bool,
    setup_exe: str | None = None,
) -> dict[str, object]:
    logs = log_paths_for_install()
    preview = owned_paths_preview()

    if not final_confirm:
        return {
            "status": "aborted",
            "reason": "final_confirm must be true after the owner's second confirmation step.",
            "log_paths": logs,
            "preview": preview,
        }

    token_error = verify_confirm_token(confirm_token, acknowledged_roots)
    if token_error:
        return {
            "status": "aborted",
            "reason": token_error,
            "log_paths": logs,
            "preview": preview,
        }

    if sys.platform != "win32":
        return {
            "status": "aborted",
            "reason": "Clean Install / Reinstall is only available on Windows.",
            "log_paths": logs,
            "preview": preview,
        }

    script = clean_reinstall_script_path()
    force_stop = force_stop_script_path()
    if not script.is_file():
        return {
            "status": "aborted",
            "reason": f"Missing helper script: {script}",
            "log_paths": logs,
            "preview": preview,
        }
    if not force_stop.is_file():
        return {
            "status": "aborted",
            "reason": "force-stop-jarvis.ps1 is missing; clean reinstall aborted.",
            "log_paths": logs,
            "preview": preview,
        }

    install = preview.get("install_root") or ""
    roots = preview.get("owned_root_entries") or []
    paths = [str(entry.get("path") or "") for entry in roots if isinstance(entry, dict)]
    if not paths:
        return {
            "status": "aborted",
            "reason": "No safe Jarvis-owned roots to wipe.",
            "log_paths": logs,
            "preview": preview,
        }

    write_status_file(status="running", exit_reason="")

    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-InstallRoot",
        str(install),
        "-Mode",
        "Portal",
        "-SkipConfirm",
    ]
    setup_path = setup_exe or str(preview.get("setup_exe") or "")
    if setup_path:
        args.extend(["-SetupExePath", setup_path])

    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]

    try:
        subprocess.Popen(  # noqa: S603
            args,
            cwd=str(install),
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        LOG.exception("clean reinstall launch failed")
        write_status_file(status="failed", exit_reason="setup-launch-failed")
        return {
            "status": "aborted",
            "reason": str(exc),
            "log_paths": logs,
            "preview": preview,
        }

    return {
        "status": "started",
        "message": "Clean reinstall helper started detached. Jarvis may stop immediately.",
        "log_paths": logs,
        "poll_path": "/api/installer/clean-reinstall/status",
        "preview": preview,
    }
