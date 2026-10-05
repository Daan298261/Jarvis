"""Whether the Jarvis backend process is running elevated."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

LOGON_TASK_NAME = "JarvisElevatedBackend"

# schtasks can take up to several seconds; /api/health is polled every ~500ms
# during cold start. Cache the registration probe so readiness stays cheap.
_LOGON_TASK_CACHE_TTL_S = 30.0
_logon_task_lock = threading.Lock()
_logon_task_cached: bool | None = None
_logon_task_cached_at = 0.0


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


def invalidate_logon_task_cache() -> None:
    """Drop the cached schtasks result (call after register/unregister)."""
    global _logon_task_cached, _logon_task_cached_at
    with _logon_task_lock:
        _logon_task_cached = None
        _logon_task_cached_at = 0.0


def _query_logon_task_registered() -> bool:
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


def logon_task_registered(*, force: bool = False) -> bool:
    """Cached schtasks probe used by /api/health and elevation snapshots.

    ``force=True`` always re-queries and atomically replaces the cached value
    and timestamp so later unforced reads see the fresh probe.
    """
    global _logon_task_cached, _logon_task_cached_at
    if os.name != "nt":
        return False
    now = time.monotonic()
    with _logon_task_lock:
        if (
            not force
            and _logon_task_cached is not None
            and (now - _logon_task_cached_at) < _LOGON_TASK_CACHE_TTL_S
        ):
            return _logon_task_cached
    registered = _query_logon_task_registered()
    with _logon_task_lock:
        _logon_task_cached = registered
        _logon_task_cached_at = time.monotonic()
    return registered


def snapshot(*, force: bool = False) -> dict[str, object]:
    """Elevation + logon-task status. ``force`` refreshes the schtasks cache first."""
    registered = logon_task_registered(force=force)
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
    if os.name != "nt":
        snap = snapshot()
        return {**snap, "ok": False, "prompted": False, "detail": "Full PC control uses a Windows logon task."}
    # Force-refresh so the returned payload matches the boolean check (not a stale cache).
    snap = snapshot(force=True)
    if is_elevated() and snap["logon_task_registered"]:
        return {**snap, "ok": True, "prompted": False, "detail": "Jarvis already has administrator on this session."}
    # Prefer os.path over pathlib: tests patch os.name to "nt" on Linux, which
    # makes pathlib.Path construct WindowsPath and Path.resolve() raise.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    script = os.path.join(root, "start-jarvis.ps1")
    params = (
        "-NoProfile -ExecutionPolicy Bypass -File "
        f'"{script}" -RegisterLogonTask -NoBrowser'
    )
    try:
        import ctypes

        rc = int(ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, root, 1))
    except Exception as exc:  # noqa: BLE001 — UAC UI is best-effort
        invalidate_logon_task_cache()
        return {**snapshot(force=True), "ok": False, "prompted": False, "detail": str(exc)[:240]}
    prompted = rc > 32
    # Owner may approve registration; drop stale negative cache then rebuild.
    invalidate_logon_task_cache()
    return {
        **snapshot(force=True),
        "ok": prompted,
        "prompted": prompted,
        "detail": (
            "Windows will ask once. Approve it so Jarvis can control this PC."
            if prompted
            else "Windows did not show the administrator prompt."
        ),
    }
