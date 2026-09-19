"""Dedicated thread pool for the fast front/chat model lane (always available)."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-companion")


def run_companion_sync(fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> asyncio.Future[_T]:
    """Schedule blocking companion-lane work off the main event loop."""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(_EXECUTOR, lambda: fn(*args, **kwargs))


async def run_companion_async(coro_factory: Callable[[], Any]) -> Any:
    """Run an async factory on the companion thread's loop bridge (sync entry only)."""
    return await run_companion_sync(coro_factory)
