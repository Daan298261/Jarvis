from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import data_dir

_STATE_VERSION = 1
_MAX_RECENT = 48
_MAX_SEMANTIC_HASHES = 64


def _empty_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "last_global_comment_at": None,
        "topic_last_comment_at": {},
        "fact_last_comment_at": {},
        "semantic_hashes": [],
        "suppressed_topics": {},
        "sarcasm_penalty_until": None,
        "recent": [],
        "preference_bias": 0,
    }


class CommentaryStateStore:
    """Cooldown, feedback, and recent intent history for RFC-0055."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "commentary_state.json")
        self._lock = threading.RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._load_unlocked())

    def mutate(self, fn) -> Any:
        with self._lock:
            state = self._load_unlocked()
            result = fn(state)
            self._save_unlocked(state)
            return result

    def reset(self) -> dict[str, Any]:
        def apply(state: dict[str, Any]) -> dict[str, Any]:
            state.clear()
            state.update(_empty_state())
            return deepcopy(state)

        return self.mutate(apply)

    def snapshot(self) -> dict[str, Any]:
        state = self.load()
        return {
            "version": state.get("version", _STATE_VERSION),
            "recent_count": len(state.get("recent") or []),
            "suppressed_topic_count": len(state.get("suppressed_topics") or {}),
            "last_global_comment_at": state.get("last_global_comment_at"),
            "preference_bias": state.get("preference_bias", 0),
        }

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_state()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_state()
        if not isinstance(payload, dict) or payload.get("version") != _STATE_VERSION:
            return _empty_state()
        payload.setdefault("topic_last_comment_at", {})
        payload.setdefault("fact_last_comment_at", {})
        payload.setdefault("semantic_hashes", [])
        payload.setdefault("suppressed_topics", {})
        payload.setdefault("recent", [])
        payload.setdefault("preference_bias", 0)
        return payload

    def _save_unlocked(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state["version"] = _STATE_VERSION
        recent = list(state.get("recent") or [])
        if len(recent) > _MAX_RECENT:
            state["recent"] = recent[-_MAX_RECENT:]
        hashes = list(state.get("semantic_hashes") or [])
        if len(hashes) > _MAX_SEMANTIC_HASHES:
            state["semantic_hashes"] = hashes[-_MAX_SEMANTIC_HASHES:]
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


def append_recent_record(state: dict[str, Any], record: dict[str, Any]) -> None:
    recent = state.setdefault("recent", [])
    recent.append(record)
    if len(recent) > _MAX_RECENT:
        state["recent"] = recent[-_MAX_RECENT:]
