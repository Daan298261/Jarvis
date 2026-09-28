"""Whether the Jarvis backend process is running elevated."""

from __future__ import annotations

import os
import subprocess
import sys

LOGON_TASK_NAME = "JarvisElevatedBackend"


def is_elevated() -> bool:
    if os.name != "nt":
        try:
            return os.geteuid() == 0  # type: ignore[attr-defined]
        except AttributeError:
            return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def logon_task_registered() -> bool:
    """True when the elevated logon scheduled task exists on this Windows host."""
    if os.name != "nt":
        return False
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            ["schtasks", "/Query", "/TN", LOGON_TASK_NAME],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def snapshot() -> dict[str, object]:
    registered = logon_task_registered()
    elevated = is_elevated()
    hint = ""
    if not registered:
        hint = "Run .\\start-jarvis.ps1 -RegisterLogonTask as administrator once, then log on again."
    elif not elevated:
        hint = "Logon task is registered; this process is not elevated yet (restart after logon or start from the task)."
    return {
        "elevated": elevated,
        "pid": os.getpid(),
        "executable": sys.executable,
        "platform": os.name,
        "logon_task": LOGON_TASK_NAME,
        "logon_task_registered": registered,
        "logon_task_hint": hint,
    }
