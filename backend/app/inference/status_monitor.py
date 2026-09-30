"""Background model/runtime status monitor with an honest in-process cache.

Hot-path readers (GET /api/model, system/diagnostics HUD) must not block on
nvidia-smi + HTTP health probes every request. This module:

- refreshes a snapshot on a background interval
- serves fresh/stale cached snapshots with age markers
- fail-closes (healthy=False) when never successfully probed
- never invents LLM load progress percentages
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from ..config import AppSettings, load_settings

logger = logging.getLogger("jarvis.inference.status_monitor")

CacheStatus = Literal["fresh", "stale", "miss", "error"]

# Serve without re-probing.
DEFAULT_FRESH_TTL_SECONDS = 2.0
# Serve marked stale; kick a non-blocking background refresh.
DEFAULT_STALE_TTL_SECONDS = 15.0
# Beyond this, the request path may await one refresh.
DEFAULT_HARD_TTL_SECONDS = 60.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0

# Cheap in-memory fields overlaid on a cached probe so load/unload flips show
# immediately without inventing progress %.
_LIVE_STATE_KEYS = (
    "loaded",
    "loading",
    "last_error",
    "profile",
    "pid",
    "model_path",
    "mmproj_path",
    "vision_loaded",
    "context_size",
    "server_n_ctx",
    "load_time_seconds",
    "tokens_per_second",
    "prompt_tokens_per_second",
    "advertised_models",
    "health_path",
    "remote_model",
    "inference_backend",
    "manages_process",
    "family",
    "thinking_mode",
    "quantization",
    "active_model",
)


@dataclass
class StatusCacheEntry:
    snapshot: dict[str, Any]
    probed_at_mono: float
    probed_at_iso: str
    probe_ok: bool
    last_probe_error: str = ""


@dataclass
class ModelStatusMonitor:
    fresh_ttl_seconds: float = DEFAULT_FRESH_TTL_SECONDS
    stale_ttl_seconds: float = DEFAULT_STALE_TTL_SECONDS
    hard_ttl_seconds: float = DEFAULT_HARD_TTL_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    _entry: StatusCacheEntry | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _refresh_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _loop_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    _probe_count: int = field(default=0, init=False, repr=False)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._running = False
            return
        self._loop_task = loop.create_task(self._poll_loop(), name="jarvis-model-status-monitor")

    def stop(self) -> None:
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        self._loop_task = None
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = None

    def reset_for_tests(self) -> None:
        self.stop()
        self._entry = None
        self._probe_count = 0
        self.fresh_ttl_seconds = DEFAULT_FRESH_TTL_SECONDS
        self.stale_ttl_seconds = DEFAULT_STALE_TTL_SECONDS
        self.hard_ttl_seconds = DEFAULT_HARD_TTL_SECONDS
        self.poll_interval_seconds = DEFAULT_POLL_INTERVAL_SECONDS

    def invalidate(self) -> None:
        self._entry = None

    @property
    def probe_count(self) -> int:
        return self._probe_count

    def cache_age_seconds(self) -> float | None:
        if self._entry is None:
            return None
        return max(0.0, time.monotonic() - self._entry.probed_at_mono)

    def _classify(self, age: float | None) -> CacheStatus:
        if age is None or self._entry is None:
            return "miss"
        if not self._entry.probe_ok:
            return "error"
        if age <= self.fresh_ttl_seconds:
            return "fresh"
        if age <= self.stale_ttl_seconds:
            return "stale"
        return "stale"

    def _decorate(self, snapshot: dict[str, Any], status: CacheStatus, *, age: float | None) -> dict[str, Any]:
        out = copy.deepcopy(snapshot)
        # Never invent load progress; strip if a probe ever added one by mistake.
        out.pop("load_progress_percent", None)
        out.pop("loading_percent", None)
        out.pop("progress_percent", None)
        age_ms = None if age is None else int(round(age * 1000))
        entry = self._entry
        out["status_cache"] = {
            "age_ms": age_ms,
            "status": status,
            "stale": status in {"stale", "error", "miss"},
            "probe_ok": bool(entry.probe_ok) if entry is not None else False,
            "probed_at": entry.probed_at_iso if entry is not None else None,
            "last_probe_error": (entry.last_probe_error if entry is not None else "") or "",
            "fresh_ttl_seconds": self.fresh_ttl_seconds,
            "stale_ttl_seconds": self.stale_ttl_seconds,
            "hard_ttl_seconds": self.hard_ttl_seconds,
            "monitor_running": self._running,
        }
        return out

    def _overlay_live_state(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Merge cheap InferenceState fields; keep probed healthy/vram from cache."""
        from .manager import MANAGER

        live = MANAGER.live_state_overlay()
        out = dict(snapshot)
        for key in _LIVE_STATE_KEYS:
            if key in live:
                out[key] = live[key]
        # Fail-closed: never claim healthy from overlay alone.
        if "healthy" not in out:
            out["healthy"] = False
        out.pop("load_progress_percent", None)
        out.pop("loading_percent", None)
        out.pop("progress_percent", None)
        return out

    def _fail_closed_snapshot(self, settings: AppSettings, error: str) -> dict[str, Any]:
        from .manager import MANAGER

        base = MANAGER.unprobed_snapshot(settings)
        base["healthy"] = False
        if error:
            base["last_error"] = error
        return base

    def _schedule_refresh(self, settings: AppSettings) -> None:
        if self._refresh_task and not self._refresh_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _runner() -> None:
            try:
                await self.refresh(settings)
            except Exception:
                logger.debug("background model status refresh failed", exc_info=True)

        self._refresh_task = loop.create_task(_runner(), name="jarvis-model-status-refresh")

    async def refresh(self, settings: AppSettings | None = None) -> dict[str, Any]:
        """Run a full live probe and store the result. Failures do not soft-pass healthy."""
        settings = settings or load_settings()
        async with self._lock:
            from .manager import MANAGER

            self._probe_count += 1
            try:
                snap = await MANAGER.live_snapshot(settings)
                # Honesty: live_snapshot already sets healthy from the probe.
                if "healthy" not in snap:
                    snap["healthy"] = False
                now = time.monotonic()
                self._entry = StatusCacheEntry(
                    snapshot=snap,
                    probed_at_mono=now,
                    probed_at_iso=datetime.now(timezone.utc).isoformat(),
                    probe_ok=True,
                    last_probe_error="",
                )
                return self._decorate(self._overlay_live_state(snap), "fresh", age=0.0)
            except Exception as exc:
                message = str(exc)[:500] or "model status probe failed"
                logger.debug("model status probe failed: %s", message, exc_info=True)
                if self._entry is not None and self._entry.probe_ok:
                    # Keep last successful fields but force healthy=False — do not soft-pass.
                    degraded = copy.deepcopy(self._entry.snapshot)
                    degraded["healthy"] = False
                    degraded["last_error"] = message
                    self._entry = StatusCacheEntry(
                        snapshot=degraded,
                        probed_at_mono=time.monotonic(),
                        probed_at_iso=datetime.now(timezone.utc).isoformat(),
                        probe_ok=False,
                        last_probe_error=message,
                    )
                    age = 0.0
                    return self._decorate(self._overlay_live_state(degraded), "error", age=age)
                fail = self._fail_closed_snapshot(settings, message)
                self._entry = StatusCacheEntry(
                    snapshot=fail,
                    probed_at_mono=time.monotonic(),
                    probed_at_iso=datetime.now(timezone.utc).isoformat(),
                    probe_ok=False,
                    last_probe_error=message,
                )
                return self._decorate(fail, "miss", age=0.0)

    async def get_snapshot(
        self,
        settings: AppSettings | None = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Prefer cache; block only on miss or age beyond hard TTL (or force)."""
        settings = settings or load_settings()
        if force_refresh:
            return await self.refresh(settings)

        age = self.cache_age_seconds()
        status = self._classify(age)

        if status == "fresh" and self._entry is not None and self._entry.probe_ok:
            return self._decorate(self._overlay_live_state(self._entry.snapshot), "fresh", age=age)

        if status == "stale" and self._entry is not None and age is not None and age <= self.stale_ttl_seconds:
            self._schedule_refresh(settings)
            return self._decorate(self._overlay_live_state(self._entry.snapshot), "stale", age=age)

        if (
            self._entry is not None
            and self._entry.probe_ok
            and age is not None
            and age <= self.hard_ttl_seconds
        ):
            # Past soft stale TTL but within hard TTL: still serve, refresh in background.
            self._schedule_refresh(settings)
            return self._decorate(self._overlay_live_state(self._entry.snapshot), "stale", age=age)

        # Miss, error without usable entry, or beyond hard TTL → await one refresh.
        return await self.refresh(settings)

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self.refresh(load_settings())
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("model status monitor loop error", exc_info=True)
            try:
                await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                break


STATUS_MONITOR = ModelStatusMonitor()
