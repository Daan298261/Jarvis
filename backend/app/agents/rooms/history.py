"""Private persona history for Agent Rooms (RFC-0174).

Each participant keeps a private transcript that is never merged into the
shared Blackboard. Only explicit, sanitized publishes reach shared state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .protocol import sanitize_public_text, strip_hidden_fields


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PrivateTurn:
    agent_id: str
    role: str
    content: str
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": strip_hidden_fields(self.metadata),
        }


class PrivateHistoryStore:
    """Per-agent private turns; isolated from Blackboard."""

    def __init__(self, *, max_turns_per_agent: int = 200) -> None:
        if max_turns_per_agent < 1:
            raise ValueError("max_turns_per_agent must be >= 1")
        self.max_turns_per_agent = int(max_turns_per_agent)
        self._by_agent: dict[str, list[PrivateTurn]] = {}

    def append(
        self,
        agent_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> PrivateTurn:
        aid = str(agent_id or "").strip().lower()
        if not aid:
            raise ValueError("agent_id is required")
        text = sanitize_public_text(content)
        if not text:
            raise ValueError("content is required")
        turn = PrivateTurn(
            agent_id=aid,
            role=str(role or "assistant").strip().lower() or "assistant",
            content=text,
            created_at=_utcnow().astimezone(timezone.utc).isoformat(),
            metadata=strip_hidden_fields(metadata),
        )
        bucket = self._by_agent.setdefault(aid, [])
        bucket.append(turn)
        if len(bucket) > self.max_turns_per_agent:
            del bucket[0 : len(bucket) - self.max_turns_per_agent]
        return turn

    def get(self, agent_id: str) -> list[PrivateTurn]:
        aid = str(agent_id or "").strip().lower()
        return list(self._by_agent.get(aid, []))

    def agents(self) -> list[str]:
        return sorted(self._by_agent.keys())

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {aid: [t.as_dict() for t in turns] for aid, turns in self._by_agent.items()}
