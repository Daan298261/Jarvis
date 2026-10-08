"""In-flight inference lease: shared for chat, exclusive for local reloads."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class RequestLease:
    """RW-style gate so a reload cannot run while any request is in flight.

    ``shared`` is held for the whole of ``chat`` / ``chat_stream``.
    ``exclusive`` refuses immediately if a shared or exclusive holder exists;
    while held it blocks new shared leases until the reload finishes.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._shared = 0
        self._exclusive = False
        self._readers_allowed = asyncio.Event()
        self._readers_allowed.set()

    @property
    def in_flight(self) -> bool:
        return self._shared > 0 or self._exclusive

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        async with self._lock:
            while self._exclusive:
                self._lock.release()
                await self._readers_allowed.wait()
                await self._lock.acquire()
            self._shared += 1
        try:
            yield
        finally:
            async with self._lock:
                self._shared -= 1

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[bool]:
        async with self._lock:
            if self._shared > 0 or self._exclusive:
                acquired = False
            else:
                self._exclusive = True
                self._readers_allowed.clear()
                acquired = True
        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            async with self._lock:
                self._exclusive = False
                self._readers_allowed.set()
