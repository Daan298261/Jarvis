"""Replayable collaboration audit for Agent Rooms (RFC-0174).

Audit events reconstruct the room without exposing hidden chain-of-thought.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .protocol import strip_hidden_fields

AUDIT_KINDS = (
    "room_created",
    "participant_joined",
    "message_posted",
    "blackboard_write",
    "handoff",
    "deadlock_detected",
    "deadlock_resolved",
    "governor_denied",
    "governor_acquired",
    "governor_released",
    "synthesis",
    "room_terminated",
    "owner_escalation",
    "task_assigned",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AuditEvent:
    id: str
    room_id: str
    kind: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "kind": self.kind,
            "summary": self.summary,
            "payload": strip_hidden_fields(self.payload),
            "created_at": self.created_at,
        }


class RoomAuditLog:
    """In-memory append-only audit log for one room (or a shared registry)."""

    def __init__(self, *, max_events: int = 2000) -> None:
        self.max_events = max(1, int(max_events))
        self._lock = threading.RLock()
        self._events: list[AuditEvent] = []

    def record(
        self,
        *,
        room_id: str,
        kind: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> AuditEvent:
        kind_text = str(kind or "").strip().lower()
        if kind_text not in AUDIT_KINDS:
            raise ValueError(f"Unknown audit kind: {kind!r}")
        event = AuditEvent(
            id=event_id or str(uuid.uuid4()),
            room_id=str(room_id),
            kind=kind_text,
            summary=str(summary or "").strip()[:400],
            payload=strip_hidden_fields(payload),
            created_at=_utcnow().astimezone(timezone.utc).isoformat(),
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events :]
        return event

    def list_events(self, room_id: str | None = None, *, limit: int | None = None) -> list[AuditEvent]:
        with self._lock:
            rows = list(self._events)
        if room_id:
            rows = [e for e in rows if e.room_id == room_id]
        if limit is not None:
            rows = rows[-max(1, int(limit)) :]
        return rows

    def replay(self, room_id: str) -> dict[str, Any]:
        """Rebuild an owner-safe collaboration timeline from audit events."""
        events = self.list_events(room_id)
        participants: list[str] = []
        messages: list[dict[str, Any]] = []
        blackboard_writes: list[dict[str, Any]] = []
        handoffs: list[dict[str, Any]] = []
        deadlocks: list[dict[str, Any]] = []
        synthesis: dict[str, Any] | None = None
        terminated = False
        escalated = False
        for event in events:
            payload = strip_hidden_fields(event.payload)
            # Defense in depth: never leak hidden keys even if slipped in.
            assert not any(
                k in payload
                for k in (
                    "reasoning",
                    "reasoning_content",
                    "chain_of_thought",
                    "thinking",
                    "cot",
                )
            )
            if event.kind == "participant_joined":
                agent = str(payload.get("agent_id") or "").lower()
                if agent and agent not in participants:
                    participants.append(agent)
            elif event.kind == "message_posted":
                messages.append(payload)
            elif event.kind == "blackboard_write":
                blackboard_writes.append(payload)
            elif event.kind == "handoff":
                handoffs.append(payload)
            elif event.kind in {"deadlock_detected", "deadlock_resolved"}:
                deadlocks.append({"kind": event.kind, **payload})
            elif event.kind == "synthesis":
                synthesis = payload
            elif event.kind == "room_terminated":
                terminated = True
            elif event.kind == "owner_escalation":
                escalated = True
        return {
            "room_id": room_id,
            "participants": participants,
            "messages": messages,
            "blackboard_writes": blackboard_writes,
            "handoffs": handoffs,
            "deadlocks": deadlocks,
            "synthesis": synthesis,
            "terminated": terminated,
            "escalated": escalated,
            "event_count": len(events),
            "events": [e.as_dict() for e in events],
        }
