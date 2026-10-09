"""Bounded System-One evaluation at command intake (RFC-0171 / RFC-0206).

``evaluate_request_route`` is a thin wrapper around ``decide_owner_turn`` so
the agent loop and owner chat share one path. The encoder chooses a parser,
never permissions or executable tool arguments.
"""
from __future__ import annotations

import logging

from ..decision.owner_turn import OWNER_TURN_DEADLINE_MS, decide_owner_turn
from .planning import RequestRoute

log = logging.getLogger(__name__)
INTAKE_DEADLINE_MS = OWNER_TURN_DEADLINE_MS


async def evaluate_request_route(
    prompt: str,
    baseline: RequestRoute,
    *,
    settings=None,
    decision_tier: str = "",
) -> RequestRoute:
    """Always runs one Reflex ``decide()`` (50 ms cap) then returns the route."""
    try:
        turn = await decide_owner_turn(
            prompt,
            baseline=baseline,
            settings=settings,
            decision_tier=decision_tier,
        )
        return turn.route
    except Exception:
        log.warning("Command intake provider unavailable; using deterministic route", exc_info=True)
        return baseline
