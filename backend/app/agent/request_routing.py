"""Bounded System-One evaluation at command intake (RFC-0171 / RFC-0206).

``evaluate_request_route`` is the shared call-site around ``decide_owner_turn``
so the agent loop, owner chat, and front lane share one path. The encoder
chooses a parser, never permissions or executable tool arguments.
"""
from __future__ import annotations

import logging

from ..decision.owner_turn import (
    OwnerTurnDecision,
    decide_owner_turn,
    front_action_for_shape,
    infer_rules_reply_shape,
)
from .planning import RequestRoute, route_request

log = logging.getLogger(__name__)


async def evaluate_request_route(
    prompt: str,
    baseline: RequestRoute | None = None,
    *,
    settings=None,
    decision_tier: str = "",
) -> OwnerTurnDecision:
    """Always runs one Reflex ``decide()`` (50 ms cap) then returns the turn."""
    resolved = baseline or route_request(prompt or "")
    try:
        return await decide_owner_turn(
            prompt,
            baseline=resolved,
            settings=settings,
            decision_tier=decision_tier,
        )
    except Exception:
        log.warning("Command intake provider unavailable; using deterministic route", exc_info=True)
        shape = infer_rules_reply_shape(prompt or "", baseline_route=resolved.kind)
        return OwnerTurnDecision(
            route=resolved,
            reply_shape=shape,
            front_action=front_action_for_shape(shape),
        )
