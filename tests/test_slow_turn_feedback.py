from __future__ import annotations

import asyncio

import pytest

from app.persona.slow_turn_feedback import NUDGE_AFTER_SECONDS, SlowTurnNudger


@pytest.mark.asyncio
async def test_nudger_cancels_cleanly():
    nudger = SlowTurnNudger("hello", started=asyncio.get_event_loop().time())
    nudger.start()
    meta = await nudger.stop()
    assert meta["nudges"] == 0


def test_nudge_threshold_is_sixty_seconds():
    assert NUDGE_AFTER_SECONDS == 60.0
