"""RFC-0124: Detached launch of clean-reinstall-jarvis.ps1 (portal / recovery CTA)."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from ..config import repo_root
from .owned_paths import owned_paths_preview, registered_owned_roots, resolve_install_root

LOG = logging.getLogger(__name__)


def clean_reinstall_script_path() -> Path:
    return repo_root() / "installer" / "windows" / "clean-reinstall-jarvis.ps1"


def force_stop_script_path() -> Path:
    return repo_root() / "installer" / "windows" / "force-stop-jarvis.ps1"


def start_clean_reinstall_detached(*, setup_exe: str | None = None) -> dict[str, object]:
    preview = owned_paths_preview()
    if sys.platform != "win32":
        return {
            "ok": False,
            "error": "Clean Install / Reinstall is only available on Windows.",
            "preview": preview,
        }

    script = clean_reinstall_script_path()
    force_stop = force_stop_script_path()
    if not script.is_file():
        return {"ok": False, "error": f"Missing helper script: {script}", "preview": preview}
    if not force_stop.is_file():
        return {
            "ok": False,
            "error": "force-stop-jarvis.ps1 is missing; clean reinstall aborted.",
            "preview": preview,
        }

    install = resolve_install_root()
    roots = registered_owned_roots(install_root=install)
    if not roots:
        return {"ok": False, "error": "No safe Jarvis-owned roots to wipe.", "preview": preview}

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
    if setup_exe:
        args.extend(["-SetupExePath", setup_exe])
    elif preview.get("setup_exe"):
        args.extend(["-SetupExePath", str(preview["setup_exe"])])

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
        return {"ok": False, "error": str(exc), "preview": preview}

    return {
        "ok": True,
        "message": "Clean reinstall started in a detached helper. Jarvis will stop shortly.",
        "log_hint": "%TEMP%\\Jarvis-clean-reinstall.log",
        "owned_roots": [str(p) for p in roots],
        "preview": preview,
    }
