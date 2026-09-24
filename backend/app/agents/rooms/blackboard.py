"""Bounded shared Blackboard for Agent Rooms (RFC-0174).

Stores only approved task facts, artifacts, decisions, and citations.
Private persona history must never be written here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .protocol import sanitize_public_text, strip_hidden_fields


class BlackboardKind(str, Enum):
    FACT = "fact"
    ARTIFACT = "artifact"
    DECISION = "decision"
    CITATION = "citation"


DEFAULT_MAX_ENTRIES = 64
DEFAULT_MAX_ENTRY_CHARS = 4000
DEFAULT_MAX_TOTAL_CHARS = 48_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BlackboardEntry:
    id: str
    kind: BlackboardKind
    key: str
    content: str
    author: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "key": self.key,
            "content": self.content,
            "author": self.author,
            "metadata": strip_hidden_fields(self.metadata),
            "created_at": self.created_at,
        }

    def char_size(self) -> int:
        return len(self.content) + len(self.key) + len(str(self.metadata))


class BlackboardBoundError(ValueError):
    """Raised when a write would exceed blackboard bounds."""


class Blackboard:
    """Bounded, owner-visible shared task state."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_entry_chars: int = DEFAULT_MAX_ENTRY_CHARS,
        max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if max_entry_chars < 32:
            raise ValueError("max_entry_chars must be >= 32")
        if max_total_chars < max_entry_chars:
            raise ValueError("max_total_chars must be >= max_entry_chars")
        self.max_entries = int(max_entries)
        self.max_entry_chars = int(max_entry_chars)
        self.max_total_chars = int(max_total_chars)
        self._entries: dict[str, BlackboardEntry] = {}
        self._order: list[str] = []

    def _total_chars(self) -> int:
        return sum(entry.char_size() for entry in self._entries.values())

    def publish(
        self,
        *,
        kind: str | BlackboardKind,
        key: str,
        content: str,
        author: str,
        metadata: dict[str, Any] | None = None,
        entry_id: str | None = None,
    ) -> BlackboardEntry:
        author_id = str(author or "").strip().lower()
        if not author_id:
            raise ValueError("author is required")
        key_text = sanitize_public_text(key)
        if not key_text:
            raise ValueError("key is required")
        body = sanitize_public_text(content)
        if not body:
            raise ValueError("content is required")
        if len(body) > self.max_entry_chars:
            raise BlackboardBoundError(
                f"entry content exceeds max_entry_chars ({self.max_entry_chars})"
            )
        kind_enum = kind if isinstance(kind, BlackboardKind) else BlackboardKind(str(kind).strip().lower())
        meta = strip_hidden_fields(metadata)
        entry = BlackboardEntry(
            id=entry_id or str(uuid.uuid4()),
            kind=kind_enum,
            key=key_text[:120],
            content=body,
            author=author_id,
            metadata=meta,
            created_at=_utcnow().astimezone(timezone.utc).isoformat(),
        )
        # Replace same key+kind (latest wins) without counting as growth.
        existing_id = None
        for eid, existing in self._entries.items():
            if existing.kind == entry.kind and existing.key == entry.key:
                existing_id = eid
                break
        projected = self._entries.copy()
        if existing_id:
            projected.pop(existing_id, None)
        projected[entry.id] = entry
        if len(projected) > self.max_entries:
            raise BlackboardBoundError(
                f"blackboard entry cap exceeded ({self.max_entries})"
            )
        total = sum(e.char_size() for e in projected.values())
        if total > self.max_total_chars:
            raise BlackboardBoundError(
                f"blackboard total char budget exceeded ({self.max_total_chars})"
            )
        if existing_id:
            self._entries.pop(existing_id, None)
            if existing_id in self._order:
                self._order.remove(existing_id)
        self._entries[entry.id] = entry
        self._order.append(entry.id)
        return entry

    def get(self, entry_id: str) -> BlackboardEntry | None:
        return self._entries.get(entry_id)

    def list(
        self,
        *,
        kind: str | BlackboardKind | None = None,
        author: str | None = None,
    ) -> list[BlackboardEntry]:
        kind_filter: BlackboardKind | None = None
        if kind is not None:
            kind_filter = kind if isinstance(kind, BlackboardKind) else BlackboardKind(str(kind).strip().lower())
        author_id = str(author).strip().lower() if author else None
        out: list[BlackboardEntry] = []
        for eid in self._order:
            entry = self._entries[eid]
            if kind_filter is not None and entry.kind != kind_filter:
                continue
            if author_id is not None and entry.author != author_id:
                continue
            out.append(entry)
        return out

    def snapshot(self) -> dict[str, Any]:
        entries = [e.as_dict() for e in self.list()]
        return {
            "entries": entries,
            "counts": {
                "total": len(entries),
                "facts": sum(1 for e in entries if e["kind"] == "fact"),
                "artifacts": sum(1 for e in entries if e["kind"] == "artifact"),
                "decisions": sum(1 for e in entries if e["kind"] == "decision"),
                "citations": sum(1 for e in entries if e["kind"] == "citation"),
            },
            "bounds": {
                "max_entries": self.max_entries,
                "max_entry_chars": self.max_entry_chars,
                "max_total_chars": self.max_total_chars,
                "used_chars": self._total_chars(),
            },
        }

    def cite_ids(self, *, kinds: set[BlackboardKind] | None = None) -> list[str]:
        wanted = kinds or {BlackboardKind.ARTIFACT, BlackboardKind.CITATION, BlackboardKind.DECISION}
        return [e.id for e in self.list() if e.kind in wanted]
