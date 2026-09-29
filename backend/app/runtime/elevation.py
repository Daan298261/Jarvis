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
        hint = "Approve the Windows administrator prompt so Jarvis can control this PC. There is nothing to type."
    elif not elevated:
        hint = "Administrator at logon is set. Approve the Windows prompt if this session is still a standard user."
    return {
        "elevated": elevated,
        "pid": os.getpid(),
        "executable": sys.executable,
        "platform": os.name,
        "logon_task": LOGON_TASK_NAME,
        "logon_task_registered": registered,
        "logon_task_hint": hint,
        "needs_uac": (not elevated) or (not registered),
    }


def prompt_windows_uac() -> dict[str, object]:
    """Ask Windows for administrator. The owner only clicks Yes or No — no command to run."""
    snap = snapshot()
    if os.name != "nt":
        return {**snap, "ok": False, "prompted": False, "detail": "Full PC control uses a Windows logon task."}
    if is_elevated() and logon_task_registered():
        return {**snap, "ok": True, "prompted": False, "detail": "Jarvis already has administrator on this session."}
    from ..config import repo_root

    root = repo_root()
    script = root / "start-jarvis.ps1"
    params = (
        "-NoProfile -ExecutionPolicy Bypass -File "
        f'"{script}" -RegisterLogonTask -NoBrowser'
    )
    try:
        import ctypes

        rc = int(ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, str(root), 1))
    except Exception as exc:  # noqa: BLE001 — UAC UI is best-effort
        return {**snapshot(), "ok": False, "prompted": False, "detail": str(exc)[:240]}
    prompted = rc > 32
    return {
        **snapshot(),
        "ok": prompted,
        "prompted": prompted,
        "detail": (
            "Windows will ask once. Approve it so Jarvis can control this PC."
            if prompted
            else "Windows did not show the administrator prompt."
        ),
    }
