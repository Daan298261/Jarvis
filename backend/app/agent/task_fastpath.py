"""RFC-0085 universal task fast path — hard-bypass admission and metrics.

When admission matches, the turn must complete without paying the heavy
conversation/managed pipeline (answer routing, worker stream, progress
watchdog, tool catalog, plan/verify, background verifier).

Mismatch fails closed into the normal path. Never invent answers.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .front_responder import is_safe_front_speech, worker_required
from .planning import DIRECT_LOOKUP, DIRECT_REPLY, MANAGED_TASK, RequestRoute, route_request

log = logging.getLogger("jarvis.agent.fastpath")

# Front actions that fully resolve a direct_reply without a worker.
TERMINAL_FRONT_ACTIONS = frozenset({"final_basic", "ask_clarification"})

_LOCK = threading.Lock()
_STATS: dict[str, Any] = {
    "hits": 0,
    "misses": 0,
    "by_reason": {},
    "last": None,
}


@dataclass(frozen=True)
class FastpathDecision:
    """Admission outcome for the RFC-0085 hard bypass."""

    admitted: bool
    reason: str
    route_kind: str
    front_action: str = ""
    stages_skipped: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "hit": self.admitted,
            "reason": self.reason,
            "route_kind": self.route_kind,
            "front_action": self.front_action,
            "stages_skipped": list(self.stages_skipped),
        }


@dataclass
class FastpathCounters:
    hits: int = 0
    misses: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    last: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_HEAVY_STAGES = (
    "prepare_answer_route",
    "worker_stream",
    "progress_watchdog",
    "ensure_context",
    "background_verify",
    "tool_catalog",
    "plan_verify_loop",
)


def resolve_route_kind(prompt: str, *, stored_route: str | None = None) -> str:
    """Prefer the durable task route; fall back to a fresh classification."""
    stored = (stored_route or "").strip()
    if stored in {DIRECT_REPLY, DIRECT_LOOKUP, MANAGED_TASK}:
        return stored
    return route_request(prompt).kind


def admit_fastpath(
    prompt: str,
    *,
    route_kind: str | None = None,
    route: RequestRoute | None = None,
    front_action: str = "",
    front_text: str = "",
) -> FastpathDecision:
    """Decide whether this turn may hard-bypass the heavy pipeline.

    Fail closed: any doubt returns admitted=False so the normal path runs.
    """
    kind = (route_kind or (route.kind if route else "") or "").strip()
    if not kind:
        kind = route_request(prompt).kind
    action = (front_action or "").strip()
    text = (front_text or "").strip()

    if kind == MANAGED_TASK:
        return FastpathDecision(
            admitted=False,
            reason="managed_task",
            route_kind=kind,
            front_action=action,
        )
    if kind not in {DIRECT_REPLY, DIRECT_LOOKUP}:
        return FastpathDecision(
            admitted=False,
            reason="unknown_route",
            route_kind=kind or "unknown",
            front_action=action,
        )
    if not action:
        return FastpathDecision(
            admitted=False,
            reason="missing_front_action",
            route_kind=kind,
            front_action=action,
        )
    if worker_required(action):
        # direct_lookup still needs a dedicated answer after ack; that is a
        # separate lean path, not a terminal front completion.
        return FastpathDecision(
            admitted=False,
            reason="front_requires_worker",
            route_kind=kind,
            front_action=action,
        )
    if action not in TERMINAL_FRONT_ACTIONS:
        return FastpathDecision(
            admitted=False,
            reason="non_terminal_front_action",
            route_kind=kind,
            front_action=action,
        )
    if not text:
        return FastpathDecision(
            admitted=False,
            reason="empty_front_text",
            route_kind=kind,
            front_action=action,
        )
    if not is_safe_front_speech(action, text):
        return FastpathDecision(
            admitted=False,
            reason="unsafe_front_speech",
            route_kind=kind,
            front_action=action,
        )
    if kind == DIRECT_LOOKUP:
        # Lookups must use the dedicated briefing path, not a terminal front
        # answer that could invent live facts.
        return FastpathDecision(
            admitted=False,
            reason="direct_lookup_needs_briefing",
            route_kind=kind,
            front_action=action,
        )
    return FastpathDecision(
        admitted=True,
        reason="direct_reply_terminal_front",
        route_kind=kind,
        front_action=action,
        stages_skipped=_HEAVY_STAGES,
    )


def admit_lookup_fastpath(
    prompt: str,
    *,
    route_kind: str | None = None,
    briefing: str | None = None,
) -> FastpathDecision:
    """Admit the dedicated direct_lookup lane (briefing + one answer, no verify)."""
    kind = (route_kind or "").strip() or route_request(prompt).kind
    if kind != DIRECT_LOOKUP:
        return FastpathDecision(
            admitted=False,
            reason="not_direct_lookup",
            route_kind=kind,
        )
    if not (briefing or "").strip():
        return FastpathDecision(
            admitted=False,
            reason="lookup_briefing_missing",
            route_kind=kind,
        )
    return FastpathDecision(
        admitted=True,
        reason="direct_lookup_briefing",
        route_kind=kind,
        stages_skipped=(
            "prepare_answer_route",
            "two_lane_worker_parallel",
            "progress_watchdog",
            "background_verify",
            "tool_catalog",
            "plan_verify_loop",
        ),
    )


def note_fastpath_decision(
    decision: FastpathDecision,
    *,
    task_id: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record hit/miss counters and emit a structured log line."""
    payload = decision.as_dict()
    payload["task_id"] = task_id
    payload["ts"] = round(time.time(), 3)
    if extra:
        payload.update(extra)
    with _LOCK:
        if decision.admitted:
            _STATS["hits"] = int(_STATS["hits"]) + 1
            label = "hit"
        else:
            _STATS["misses"] = int(_STATS["misses"]) + 1
            label = "miss"
        reasons: dict[str, int] = _STATS["by_reason"]  # type: ignore[assignment]
        reasons[decision.reason] = int(reasons.get(decision.reason, 0)) + 1
        _STATS["last"] = payload
    if decision.admitted:
        log.info(
            "fastpath_hit reason=%s route=%s action=%s task_id=%s skipped=%s",
            decision.reason,
            decision.route_kind,
            decision.front_action or "-",
            task_id or "-",
            ",".join(decision.stages_skipped) or "-",
        )
    else:
        log.info(
            "fastpath_miss reason=%s route=%s action=%s task_id=%s",
            decision.reason,
            decision.route_kind,
            decision.front_action or "-",
            task_id or "-",
        )
    return {"label": label, **payload}


def fastpath_stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "hits": int(_STATS["hits"]),
            "misses": int(_STATS["misses"]),
            "by_reason": dict(_STATS["by_reason"] or {}),
            "last": dict(_STATS["last"] or {}) if _STATS["last"] else None,
        }


def reset_fastpath_stats() -> None:
    with _LOCK:
        _STATS["hits"] = 0
        _STATS["misses"] = 0
        _STATS["by_reason"] = {}
        _STATS["last"] = None


def should_skip_background_verify(route_kind: str) -> bool:
    """Direct reply/lookup never schedules the background verifier."""
    return (route_kind or "").strip() in {DIRECT_REPLY, DIRECT_LOOKUP}
