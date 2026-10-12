"""Degraded-startup bookkeeping (pairing-stability fix 3).

Core startup used to run several steps bare; one exception killed the whole
backend, taking pairing, health and the companion API down with it. Steps now run
through ``run_step`` so a failure is logged, recorded, and reported by
``/api/health`` while the rest of ANZU still comes up.
"""
from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

_FAILED: dict[str, dict] = {}
_COMPLETED: list[str] = []


def reset() -> None:
    _FAILED.clear()
    _COMPLETED.clear()


async def run_step(name: str, fn: Callable[[], Any | Awaitable[Any]], default: Any = None) -> Any:
    """Run one startup step; on failure record it and return ``default``."""
    try:
        result = fn()
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        log.exception("Startup step %r failed; continuing degraded", name)
        _FAILED[name] = {"step": name, "error": f"{type(exc).__name__}: {exc}"[:500], "at": time.time()}
        return default
    _FAILED.pop(name, None)
    _COMPLETED.append(name)
    return result


def report() -> dict:
    failed = list(_FAILED.values())
    return {"degraded": bool(failed), "failed_steps": failed, "completed_steps": list(_COMPLETED)}
