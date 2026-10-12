"""ANZU core watchdog (pairing-stability fix 1/2).

The manager used to start/stop the core only on request. When the backend died
during startup nothing brought it back, so every client (pairing panel, phone)
saw a dead API. This supervisor polls core health, restarts with exponential
backoff, preserves the crashed run's error log, and records the last exit reason
so the manager and the portal can explain what happened.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

TICK_SECONDS = 10.0
STARTUP_GRACE_SECONDS = 90.0
BACKOFF_BASE_SECONDS = 15.0
BACKOFF_CAP_SECONDS = 600.0
STABLE_RESET_SECONDS = 300.0
LOG_TAIL_LINES = 40
CRASH_LOGS_KEPT = 5
LAUNCH_LOG_MAX_BYTES = 2 * 1024 * 1024
LAUNCH_LOGS_KEPT = 5


def backoff_seconds(attempt: int) -> float:
    """Delay before restart attempt N (1-based): 15, 30, 60, ... capped at 600s."""
    if attempt <= 1:
        return BACKOFF_BASE_SECONDS
    return min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))


def tail_lines(path: Path, limit: int = LOG_TAIL_LINES) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 64 * 1024))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return [line for line in text.splitlines() if line.strip()][-limit:]


def rotate_file(path: Path, keep: int, max_bytes: int = 0) -> None:
    """Shift path -> path.1 -> ... -> path.<keep>. With max_bytes, only when larger."""
    try:
        if not path.exists() or (max_bytes and path.stat().st_size < max_bytes):
            return
        oldest = path.with_name(f"{path.name}.{keep}")
        if oldest.exists():
            oldest.unlink()
        for index in range(keep - 1, 0, -1):
            src = path.with_name(f"{path.name}.{index}")
            if src.exists():
                src.replace(path.with_name(f"{path.name}.{index + 1}"))
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        log.debug("Log rotation failed for %s", path, exc_info=True)


def preserve_crash_log(logs_dir: Path, now: float) -> str | None:
    """Copy backend.err.log aside before a relaunch truncates it."""
    source = logs_dir / "backend.err.log"
    if not source.is_file() or source.stat().st_size == 0:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    target = logs_dir / f"backend-crash-{stamp}.err.log"
    try:
        shutil.copy2(source, target)
    except OSError:
        return None
    crashes = sorted(logs_dir.glob("backend-crash-*.err.log"))
    for stale in crashes[:-CRASH_LOGS_KEPT]:
        try:
            stale.unlink()
        except OSError:
            pass
    return target.name


@dataclass
class SupervisorState:
    desired_running: bool = True
    restart_attempts: int = 0
    next_restart_at: float = 0.0
    unhealthy_since: float | None = None
    healthy_since: float | None = None
    restarting: bool = False
    last_exit: dict | None = None
    last_restart_at: float | None = None
    history: list[dict] = field(default_factory=list)


class CoreSupervisor:
    def __init__(
        self,
        *,
        root: Callable[[], Path],
        healthy: Callable[[], Awaitable[bool]],
        process_present: Callable[[], bool],
        launch: Callable[[str], None],
        clock: Callable[[], float] = time.time,
        enabled: bool | None = None,
    ) -> None:
        self._root = root
        self._healthy = healthy
        self._process_present = process_present
        self._launch = launch
        self._clock = clock
        # Opt-in via env so only the real manager process (start-anzu-manager.ps1)
        # supervises the core; imports from tests or tools never launch anything.
        self.enabled = (os.environ.get("JARVIS_MANAGER_WATCHDOG") == "1") if enabled is None else enabled
        self.state = SupervisorState()
        self._task: asyncio.Task | None = None
        if self.enabled:
            self._load()

    # persistence: an explicit Stop must survive a manager restart
    def _state_path(self) -> Path:
        return self._root() / "runtime" / "manager-supervisor.json"

    def _load(self) -> None:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.state.desired_running = bool(data.get("desired_running", True))
        last_exit = data.get("last_exit")
        self.state.last_exit = last_exit if isinstance(last_exit, dict) else None

    def _save(self) -> None:
        if not self.enabled:
            return
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"desired_running": self.state.desired_running, "last_exit": self.state.last_exit}),
                encoding="utf-8",
            )
        except OSError:
            log.debug("Supervisor state save failed", exc_info=True)

    def set_desired(self, running: bool) -> None:
        self.state.desired_running = running
        if running:
            self.state.restart_attempts = 0
            self.state.next_restart_at = 0.0
        self.state.unhealthy_since = None
        self._save()

    def snapshot(self) -> dict:
        s = self.state
        now = self._clock()
        return {
            "enabled": self.enabled,
            "desired_running": s.desired_running,
            "restarting": s.restarting,
            "restart_attempts": s.restart_attempts,
            "next_restart_in_seconds": max(0, round(s.next_restart_at - now)) if s.next_restart_at > now else 0,
            "unhealthy_for_seconds": round(now - s.unhealthy_since) if s.unhealthy_since else 0,
            "last_restart_at": s.last_restart_at,
            "last_exit": s.last_exit,
        }

    async def tick(self) -> str:
        """One supervision step. Returns what happened (for tests and logs)."""
        if not self.enabled or not self.state.desired_running or self.state.restarting:
            return "idle"
        now = self._clock()
        if await self._healthy():
            s = self.state
            s.unhealthy_since = None
            if s.healthy_since is None:
                s.healthy_since = now
            if s.restart_attempts and now - s.healthy_since >= STABLE_RESET_SECONDS:
                s.restart_attempts = 0
                s.next_restart_at = 0.0
            return "healthy"
        self.state.healthy_since = None
        present = self._process_present()
        if self.state.unhealthy_since is None:
            self.state.unhealthy_since = now
        unhealthy_for = now - self.state.unhealthy_since
        if present and unhealthy_for < STARTUP_GRACE_SECONDS:
            return "starting"
        if now < self.state.next_restart_at:
            return "backoff"
        reason = (
            f"backend process exited (health failed for {round(unhealthy_for)}s)"
            if not present
            else f"backend hung: process present but unhealthy for {round(unhealthy_for)}s"
        )
        await self._restart(reason, hung=present)
        return "restarted"

    async def _restart(self, reason: str, *, hung: bool) -> None:
        s = self.state
        s.restarting = True
        now = self._clock()
        logs_dir = self._root() / "logs"
        try:
            s.last_exit = {
                "reason": reason,
                "at": now,
                "error_tail": tail_lines(logs_dir / "backend.err.log"),
                "crash_log": preserve_crash_log(logs_dir, now),
            }
            s.restart_attempts += 1
            s.next_restart_at = now + backoff_seconds(s.restart_attempts)
            s.last_restart_at = now
            s.unhealthy_since = None
            s.history = (s.history + [{"at": now, "reason": reason}])[-10:]
            self._save()
            log.warning("ANZU watchdog restarting core (attempt %s): %s", s.restart_attempts, reason)
            if hung:
                await asyncio.to_thread(self._launch, "stop")
            await asyncio.to_thread(self._launch, "start")
        except Exception as exc:  # launcher missing etc. — keep backing off, never crash the manager
            s.last_exit = {**(s.last_exit or {}), "launch_error": str(exc)}
            self._save()
            log.exception("ANZU watchdog relaunch failed")
        finally:
            s.restarting = False

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("ANZU watchdog tick failed")
            await asyncio.sleep(TICK_SECONDS)

    def start(self) -> None:
        if self.enabled and self._task is None:
            self._task = asyncio.get_running_loop().create_task(self.run_forever())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
