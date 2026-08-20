from __future__ import annotations

from .session import init_db as _init_db


async def init_db() -> None:
    await _init_db()
