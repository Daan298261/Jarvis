"""Typed inter-agent room messages (RFC-0174).

Hidden chain-of-thought is never part of the public wire format. Only concise
rationale / decision metadata may travel with a message.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ...providers.completion_text import strip_think_blocks

MESSAGE_KINDS = (
    "REQUEST",
    "RESULT",
    "QUESTION",
    "CHALLENGE",
    "HANDOFF",
    "BLOCKED",
    "FINAL",
)


class MessageKind(str, Enum):
    REQUEST = "REQUEST"
    RESULT = "RESULT"
    QUESTION = "QUESTION"
    CHALLENGE = "CHALLENGE"
    HANDOFF = "HANDOFF"
    BLOCKED = "BLOCKED"
    FINAL = "FINAL"


_HIDDEN_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "chain_of_thought",
        "chainOfThought",
        "thinking",
        "think",
        "hidden_reasoning",
        "cot",
        "scratchpad",
    }
)

_MENTION_RE = re.compile(r"@([a-z][a-z0-9_-]{0,31})", re.IGNORECASE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_public_text(text: str) -> str:
    """Strip think blocks and collapse whitespace for owner-visible text."""
    cleaned = strip_think_blocks(text or "", trim=True)
    return " ".join(cleaned.split()).strip()


def strip_hidden_fields(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Drop hidden CoT / reasoning keys from metadata dicts."""
    if not payload:
        return {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _HIDDEN_KEYS or str(key).startswith("_"):
            continue
        if isinstance(value, dict):
            out[key] = strip_hidden_fields(value)
        elif isinstance(value, str):
            out[key] = sanitize_public_text(value)
        else:
            out[key] = value
    return out


def parse_mentions(text: str) -> list[str]:
    """Return unique @mention agent ids in first-seen order (lowercased)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _MENTION_RE.finditer(text or ""):
        agent_id = match.group(1).lower()
        if agent_id in seen:
            continue
        seen.add(agent_id)
        ordered.append(agent_id)
    return ordered


def parse_message_kind(raw: str | MessageKind) -> MessageKind:
    if isinstance(raw, MessageKind):
        return raw
    text = str(raw or "").strip().upper()
    try:
        return MessageKind(text)
    except ValueError as exc:
        raise ValueError(f"Unknown room message kind: {raw!r}") from exc


@dataclass(frozen=True)
class RoomMessage:
    """Owner-visible typed room message. No hidden CoT fields."""

    id: str
    room_id: str
    kind: MessageKind
    from_agent: str
    body: str
    to_agent: str | None = None
    mentions: tuple[str, ...] = ()
    rationale: str = ""
    task_id: str | None = None
    artifact_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "kind": self.kind.value,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "mentions": list(self.mentions),
            "body": self.body,
            "rationale": self.rationale,
            "task_id": self.task_id,
            "artifact_ids": list(self.artifact_ids),
            "citation_ids": list(self.citation_ids),
            "metadata": strip_hidden_fields(self.metadata),
            "created_at": self.created_at,
        }


def build_message(
    *,
    room_id: str,
    kind: str | MessageKind,
    from_agent: str,
    body: str,
    to_agent: str | None = None,
    rationale: str = "",
    task_id: str | None = None,
    artifact_ids: list[str] | tuple[str, ...] | None = None,
    citation_ids: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
    message_id: str | None = None,
    created_at: datetime | None = None,
) -> RoomMessage:
    """Construct a sanitized RoomMessage; raises on empty from_agent or body."""
    agent = str(from_agent or "").strip().lower()
    if not agent:
        raise ValueError("from_agent is required")
    kind_enum = parse_message_kind(kind)
    public_body = sanitize_public_text(body)
    if not public_body:
        raise ValueError("message body must not be empty after sanitization")
    target = str(to_agent).strip().lower() if to_agent else None
    mentions = tuple(parse_mentions(public_body))
    if target and target not in mentions:
        mentions = (target, *mentions)
    stamp = created_at or _utcnow()
    return RoomMessage(
        id=message_id or str(uuid.uuid4()),
        room_id=str(room_id),
        kind=kind_enum,
        from_agent=agent,
        body=public_body,
        to_agent=target,
        mentions=mentions,
        rationale=sanitize_public_text(rationale),
        task_id=str(task_id) if task_id else None,
        artifact_ids=tuple(str(a) for a in (artifact_ids or ()) if str(a).strip()),
        citation_ids=tuple(str(c) for c in (citation_ids or ()) if str(c).strip()),
        metadata=strip_hidden_fields(metadata),
        created_at=stamp.astimezone(timezone.utc).isoformat(),
    )


def message_fingerprint(message: RoomMessage) -> str:
    """Stable fingerprint for cycle / duplicate detection (kind+pair+task+body)."""
    pair = f"{message.from_agent}->{message.to_agent or '*'}"
    task = message.task_id or ""
    body_key = message.body[:160].lower()
    return f"{message.kind.value}|{pair}|{task}|{body_key}"
