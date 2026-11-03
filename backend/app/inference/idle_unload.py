"""Idle unload: with Keep warm OFF, each ANZU-loaded model unloads after ``idle_unload_seconds``.

Idle time is measured per model from its own last use (``LoadedModels``), never from
the toggle and never for a model ANZU did not load. Any turn touches the main model
and the front responder. An idle release is policy, not an owner decision: it never
sets ``manually_unloaded`` and the next turn respawns what it needs on demand.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..config import AppSettings, load_settings
from .keep_alive import idle_unload_seconds, keep_warm_enabled
from .loaded_models import LOADED, LoadedModels

log = logging.getLogger(__name__)
POLL_SECONDS = 15.0

Release = Callable[[str, list[tuple[str, str]] | None], Awaitable[dict[str, Any]]]


class IdleUnload:
    def __init__(
        self,
        *,
        registry: LoadedModels = LOADED,
        poll_seconds: float = POLL_SECONDS,
        settings: Callable[[], AppSettings] = load_settings,
        release: Release | None = None,
        busy: Callable[[], bool] | None = None,
    ) -> None:
        self.registry = registry
        self.poll_seconds = poll_seconds
        self._settings = settings
        self._release = release
        self._busy = busy
        self.held = False            # something was released and no turn has happened since
        self.front_released = False  # the front responder was stopped by a release
        self.last_result: dict[str, Any] | None = None
        self.last_idle_released: list[str] = []
        self._task: asyncio.Task | None = None
        self._respawn: asyncio.Task | None = None

    # -- activity -----------------------------------------------------------------
    def touch(self) -> None:
        """A user turn starts. Like an explicit Load it clears ``manually_unloaded`` *before*
        the turn calls load / ensure_runtime / ensure_vision, so those calls are allowed for
        the turn while every background caller is still refused."""
        from .manager import MANAGER

        MANAGER.state.manually_unloaded = False
        self.registry.touch_primary()
        self.held = False
        if self.front_released:
            self.front_released = False
            self._schedule_front_restart()

    def explicit_load(self) -> None:
        """An owner Load (HUD, dropdown, runtime activation) lifts the same hold a turn does."""
        self.touch()

    def used(self) -> None:
        """A model was just used (end of a turn). Resets idle clocks without lifting any hold."""
        self.registry.touch_primary()

    def note_released(self, *, front: bool) -> None:
        self.held = True
        self.front_released = self.front_released or front

    @staticmethod
    def _manually_unloaded() -> bool:
        from .manager import MANAGER

        return bool(MANAGER.state.manually_unloaded)

    def background_blocked(self) -> bool:
        """Background starters (front restart, discovery auto-attach) stay off while released."""
        return self.held or self._manually_unloaded()

    def _schedule_front_restart(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._respawn and not self._respawn.done():
            return

        async def restart() -> None:
            from .front_runtime import FRONT_RUNTIME

            try:
                await FRONT_RUNTIME.ensure_started(self._settings())
            except Exception:
                log.exception("Front responder respawn failed")

        self._respawn = loop.create_task(restart(), name="anzu-front-respawn")

    # -- timer --------------------------------------------------------------------
    def is_busy(self) -> bool:
        if self._busy is not None:
            return self._busy()
        from ..agent.loop import AGENT

        return any(not task.done() for task in AGENT._tasks.values())

    async def tick(self) -> dict[str, Any]:
        """One timer check. Returns what it did so tests and logs can see why."""
        settings = self._settings()
        if keep_warm_enabled(settings):
            return {"action": "skipped", "reason": "keep_warm"}
        window = idle_unload_seconds(settings)
        due = [e for e in self.registry.entries() if self.registry.idle_for(e) >= window]
        if not due:
            return {"action": "skipped", "reason": "active"}
        if self.is_busy():
            return {"action": "skipped", "reason": "task_running"}
        release = self._release
        if release is None:
            from .keep_warm_release import release_models

            release = release_models
        result = await release("idle", [e.key for e in due])
        self.last_result = result
        if result.get("refused"):
            # A request or load is in flight; the next tick retries while still idle.
            return {"action": "refused", "reason": result.get("reason", "")}
        if result.get("ok"):
            self.last_idle_released = [f"{e.backend}:{e.model}" for e in due]
        else:
            # A failed release is surfaced once; the next attempt waits a full window.
            for entry in due:
                self.registry.defer(entry)
            log.warning("Idle unload failed: %s", result.get("reason"))
        return {"action": "released" if result.get("ok") else "failed", "ok": bool(result.get("ok")), "result": result}

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Idle unload check failed")
            await asyncio.sleep(self.poll_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="anzu-idle-unload")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None


IDLE_UNLOAD = IdleUnload()


UNLOADED_DETAIL = "Models are unloaded; they load again on your next turn or an explicit Load."


def warm_blocked() -> bool:
    """True while a background warm, preload or rewarm must stay silent.

    Every direct-HTTP warm (Ollama prompt-less ``/api/generate``, LM Studio load, llama-server
    warm ping, a future re-warm coordinator) asks this first. A user turn
    (``IDLE_UNLOAD.touch``) or an explicit Load (``IDLE_UNLOAD.explicit_load``) lifts it.
    """
    return IDLE_UNLOAD.background_blocked()
