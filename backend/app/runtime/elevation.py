"""Whether the Jarvis backend process is running elevated."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any

LOGON_TASK_NAME = "JarvisElevatedBackend"

# Features that require an elevated Windows backend. Non-elevated startups keep
# running; these are reported as degraded via /api/health instead of exiting.
LIMITED_WITHOUT_ELEVATION: tuple[str, ...] = (
    "kill_protected_processes",
    "elevated_app_launch",
    "close_admin_owned_apps",
    "system_firewall_wan_mapping",
)

# schtasks can take up to several seconds; /api/health is polled every ~500ms
# during cold start. Cache the registration probe so readiness stays cheap.
_LOGON_TASK_CACHE_TTL_S = 30.0
_logon_task_lock = threading.Lock()
_logon_task_cached: bool | None = None
_logon_task_cached_at = 0.0

log = logging.getLogger("jarvis.elevation")


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


def elevation_startup_plan(
    *,
    elevated: bool,
    logon_task_registered: bool,
    platform: str | None = None,
) -> dict[str, Any]:
    """Decide how a Windows start should treat elevation (no UAC automation).

    - elevated → continue with full control
    - logon task registered → prefer ``schtasks /Run`` relaunch (no UAC prompt)
    - otherwise → continue degraded (do not exit; do not auto-prompt UAC)
    """
    plat = os.name if platform is None else platform
    if plat != "nt":
        return {
            "action": "continue",
            "run_mode": "non_windows",
            "elevation_degraded": False,
            "limited_features": [],
            "detail": "Elevation applies on Windows only.",
        }
    if elevated:
        return {
            "action": "continue",
            "run_mode": "elevated",
            "elevation_degraded": False,
            "limited_features": [],
            "detail": "Running with administrator privileges.",
        }
    limited = list(LIMITED_WITHOUT_ELEVATION)
    if logon_task_registered:
        return {
            "action": "relaunch_via_logon_task",
            "run_mode": "pending_task_elevate",
            "elevation_degraded": True,
            "limited_features": limited,
            "detail": (
                f"Logon task {LOGON_TASK_NAME} is registered; prefer schtasks /Run "
                "so later starts elevate without a UAC prompt."
            ),
        }
    return {
        "action": "continue_degraded",
        "run_mode": "standard",
        "elevation_degraded": True,
        "limited_features": limited,
        "detail": (
            "Starting without administrator. Limited: "
            + ", ".join(limited)
            + ". Use Allow full PC control once to register the elevated logon task."
        ),
    }


def snapshot(*, force: bool = False) -> dict[str, object]:
    """Elevation + logon-task status. ``force`` refreshes the schtasks cache first."""
    registered = logon_task_registered(force=force)
    elevated = is_elevated()
    plan = elevation_startup_plan(
        elevated=elevated,
        logon_task_registered=registered,
        platform=os.name,
    )
    hint = ""
    if os.name == "nt" and not elevated:
        if not registered:
            hint = (
                "Jarvis is running without administrator. Use Allow full PC control "
                "once so Windows can register the elevated logon task. There is nothing to type."
            )
        else:
            hint = (
                "Administrator logon task is registered, but this process is still a "
                "standard user. Limited PC-control features stay degraded until an elevated start."
            )
    elif os.name == "nt" and elevated and not registered:
        hint = "Approve Allow full PC control once so future starts can elevate without a prompt."
    return {
        "elevated": elevated,
        "pid": os.getpid(),
        "executable": sys.executable,
        "platform": os.name,
        "logon_task": LOGON_TASK_NAME,
        "logon_task_registered": registered,
        "logon_task_hint": hint,
        "needs_uac": (os.name == "nt") and ((not elevated) or (not registered)),
        "elevation_degraded": bool(plan["elevation_degraded"]),
        "run_mode": plan["run_mode"],
        "limited_features": list(plan["limited_features"]),
        "elevation_detail": plan["detail"],
        "startup_action": plan["action"],
    }


def log_elevation_startup_status(*, force: bool = False) -> dict[str, object]:
    """Emit a clear startup log when elevated features are degraded."""
    snap = snapshot(force=force)
    if snap.get("elevation_degraded"):
        limited = ", ".join(str(item) for item in (snap.get("limited_features") or []))
        log.warning(
            "Elevation degraded (run_mode=%s): limited features: %s. %s",
            snap.get("run_mode"),
            limited or "(none)",
            snap.get("elevation_detail") or "",
        )
    else:
        log.info(
            "Elevation ok (run_mode=%s): full PC control available.",
            snap.get("run_mode"),
        )
    return snap


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
