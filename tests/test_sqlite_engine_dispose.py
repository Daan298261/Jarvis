"""Regression: reconfigure/shutdown must dispose aiosqlite pools (#531 residual)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import session as session_mod
from app.main import shutdown


@pytest.mark.asyncio
async def test_configure_database_disposes_previous_engine(tmp_path):
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    await session_mod.configure_database(path=first)
    await session_mod.init_db()
    old = session_mod.ENGINE

    async with old.connect() as conn:
        await conn.execute(text("SELECT 1"))

    await session_mod.configure_database(path=second)
    assert session_mod.ENGINE is not old
    # Pool closed: sync dispose leaves no live checked-out connections.
    assert old.sync_engine.pool.checkedout() == 0

    await session_mod.init_db()
    async with session_mod.ENGINE.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_shutdown_disposes_database_engine(tmp_path, monkeypatch):
    await session_mod.configure_database(path=tmp_path / "shutdown.db")
    await session_mod.init_db()
    engine = session_mod.ENGINE
    disposed: list[object] = []

    async def track_dispose():
        disposed.append(engine)
        await engine.dispose()

    monkeypatch.setattr(session_mod, "dispose_database_engine", track_dispose)
    # Skip unrelated shutdown side effects that need a live runtime.
    monkeypatch.setattr("app.main.QUEUE_WATCHER.stop", lambda: None)
    monkeypatch.setattr("app.main.WHATSAPP_PAIRING.close", _async_noop)
    monkeypatch.setattr("app.main.mobile_runtime.stop", _async_noop)

    await shutdown()
    assert disposed == [engine]


async def _async_noop(*_args, **_kwargs):
    return None
