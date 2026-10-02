"""Bounded System-One evaluation at command intake (RFC-0171).

The encoder chooses a parser, never permissions or executable tool arguments.
Slow/unavailable providers retain the existing deterministic route.
"""
from __future__ import annotations

import asyncio
import logging
from ..decision.reflex import decide
from ..decision.surfaces import privacy_for_tier
from ..decision.types import Question

from .planning import (
    CONVERSATION_CLASS, DIRECT_LOOKUP, DIRECT_REPLY, MANAGED_TASK, RequestRoute,
    classify_task, is_weather_query, requests_agent_tools, simple_app_control,
    simple_file_control,
)

log = logging.getLogger(__name__)
INTAKE_DEADLINE_MS = 100.0


def _evaluate(prompt: str, baseline: RequestRoute) -> RequestRoute:
    result = decide(
        {"user_message": prompt, "baseline_route": baseline.kind},
        [Question(
            id="request_route", type="choice",
            prompt="Which parser should handle this user request?",
            choices=(DIRECT_REPLY, DIRECT_LOOKUP, MANAGED_TASK),
            descriptions=(
                "Conversation: answer a greeting or knowledge question without tools",
                "Weather lookup: retrieve current weather or forecast",
                "Action: open an app, inspect or change files, browse, code, or execute a task",
            ),
        )],
        "request_routing", INTAKE_DEADLINE_MS,
        # Intake carries only the current prompt and must stay on the local
        # privacy route. Avoid loading the complete settings graph here: on a
        # cold process that alone can exceed the System-One deadline.
        privacy_for_tier("local"),
    )
    answer = result.answers.get("request_route")
    if result.fallback_used or answer is None or (answer.confidence or 0) < 0.75:
        return baseline
    # An encoder must never reclassify an explicit action as a completed answer.
    if requests_agent_tools(prompt) or simple_app_control(prompt) or simple_file_control(prompt):
        return RequestRoute(MANAGED_TASK, classify_task(prompt))
    if answer.value == DIRECT_LOOKUP:
        return RequestRoute(DIRECT_LOOKUP, CONVERSATION_CLASS) if is_weather_query(prompt) else baseline
    if answer.value == DIRECT_REPLY:
        # Keep deterministic action detection authoritative; false negatives are
        # safer than silently dropping a requested action.
        return baseline if baseline.kind == MANAGED_TASK else RequestRoute(DIRECT_REPLY, CONVERSATION_CLASS)
    if answer.value == MANAGED_TASK:
        return RequestRoute(MANAGED_TASK, classify_task(prompt))
    return baseline


async def evaluate_request_route(prompt: str, baseline: RequestRoute) -> RequestRoute:
    try:
        # Provider inference and disk-backed audit must not block the HTTP loop.
        return await asyncio.wait_for(asyncio.to_thread(_evaluate, prompt, baseline), timeout=0.15)
    except TimeoutError:
        log.info("Command intake exceeded its deadline; using deterministic route")
    except Exception:
        log.warning("Command intake provider unavailable; using deterministic route", exc_info=True)
    return baseline
