"""Orchestrator/router hooks for Agent Rooms (RFC-0174).

Keeps room-open decisions out of the hot agent loop until the portal wires
websockets; the Ornith router can still signal multi-specialist collaboration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .room import AgentRoom, create_room
from .supervisor import SUPERVISOR_ID

# Heuristic signals that a question benefits from multi-specialist collaboration.
_COLLAB_RE = re.compile(
    r"\b("
    r"collaborate|multi[- ]?agent|specialists?|swarm|"
    r"research\s+and\s+(code|implement|build)|"
    r"plan\s+and\s+(implement|build|code)|"
    r"red\s*team|blue\s*team|"
    r"@(?:" + "|".join(
        # Named specialists excluding Anzu (supervisor).
        (
            "mestor",
            "nabu",
            "enki",
            "veles",
            "themis",
            "aegir",
            "bragi",
            "hermes",
            "heimdall",
            "eir",
            "maia",
            "vulcan",
        )
    ) + r")"
    r")\b",
    re.IGNORECASE,
)

_SPECIALIST_MENTION_RE = re.compile(
    r"@(mestor|nabu|enki|veles|themis|aegir|bragi|hermes|heimdall|eir|maia|vulcan)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RoomRoutingHint:
    """Signal from the orchestrator that a room should (or should not) open."""

    open_room: bool
    specialists: tuple[str, ...] = ()
    reason: str = ""
    concurrency_budget: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "open_room": self.open_room,
            "specialists": list(self.specialists),
            "reason": self.reason,
            "concurrency_budget": self.concurrency_budget,
        }


def extract_specialist_mentions(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _SPECIALIST_MENTION_RE.finditer(text or ""):
        aid = match.group(1).lower()
        if aid in seen:
            continue
        seen.add(aid)
        ordered.append(aid)
    return ordered


def suggest_room_routing(
    user_message: str,
    *,
    router_action: str = "",
    task_class: str = "",
    explicit_specialists: list[str] | None = None,
) -> RoomRoutingHint:
    """Decide whether Ornith should open an Agent Room for this turn."""
    text = user_message or ""
    mentioned = extract_specialist_mentions(text)
    explicit = [
        str(s).strip().lower()
        for s in (explicit_specialists or [])
        if str(s).strip() and str(s).strip().lower() != SUPERVISOR_ID
    ]
    specialists = list(dict.fromkeys([*mentioned, *explicit]))

    action = str(router_action or "").strip().lower()
    if action == "delegate" and specialists:
        return RoomRoutingHint(
            open_room=True,
            specialists=tuple(specialists),
            reason="router delegate with named specialists",
            concurrency_budget=max(1, len(specialists)),
        )

    if len(specialists) >= 2:
        return RoomRoutingHint(
            open_room=True,
            specialists=tuple(specialists),
            reason="multiple @specialist mentions",
            concurrency_budget=len(specialists),
        )

    if specialists and _COLLAB_RE.search(text):
        return RoomRoutingHint(
            open_room=True,
            specialists=tuple(specialists),
            reason="collaboration cue with specialist mention",
            concurrency_budget=max(1, len(specialists)),
        )

    if action == "delegate" and _COLLAB_RE.search(text):
        # Default pair for plan+implement style work when no names given.
        defaults = ("mestor", "enki")
        return RoomRoutingHint(
            open_room=True,
            specialists=defaults,
            reason="router delegate with collaboration cue; default mestor+enki",
            concurrency_budget=2,
        )

    task = str(task_class or "").strip().lower()
    if task in {"multi_agent", "swarm", "room"} and specialists:
        return RoomRoutingHint(
            open_room=True,
            specialists=tuple(specialists),
            reason=f"task_class={task}",
            concurrency_budget=len(specialists),
        )

    return RoomRoutingHint(open_room=False, reason="single-agent path sufficient")


def open_room_from_hint(
    goal: str,
    hint: RoomRoutingHint,
    *,
    cost_mode: str = "balanced",
    privacy_mode: str = "local_only",
    room_id: str | None = None,
) -> AgentRoom:
    if not hint.open_room:
        raise ValueError("RoomRoutingHint.open_room is False")
    if not hint.specialists:
        raise ValueError("RoomRoutingHint has no specialists")
    return create_room(
        goal,
        list(hint.specialists),
        room_id=room_id,
        cost_mode=cost_mode,
        privacy_mode=privacy_mode,
    )


def attach_room_hint_to_decision(decision: Any, hint: RoomRoutingHint) -> Any:
    """Best-effort attach hint onto a RouterDecision-like object."""
    if decision is None:
        return decision
    if hasattr(decision, "__dict__"):
        try:
            decision.room_hint = hint  # type: ignore[attr-defined]
        except Exception:
            pass
    return decision
