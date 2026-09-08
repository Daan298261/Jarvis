from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import data_dir

_STATE_VERSION = 1


def _empty_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "facts": {},
        "baseline": {},
        "last_candidate_at": None,
        "last_observation_at": None,
    }


class PerceptionStateStore:
    """Persist only normalized semantic state; never raw frames or image data."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "perception_state.json")
        self._lock = threading.RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._load_unlocked())

    def save(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._save_unlocked(state)

    def mutate(self, fn) -> Any:
        """Apply one read/modify/write transaction under the process-local lock."""
        with self._lock:
            state = self._load_unlocked()
            result = fn(state)
            self._save_unlocked(state)
            return result

    def reset_state(self) -> dict[str, Any]:
        """Clear transient facts/cooldowns while preserving aggregate baseline facts."""

        def apply(state: dict[str, Any]) -> dict[str, Any]:
            baseline = deepcopy(state.get("baseline") or {})
            state.clear()
            state.update(_empty_state())
            state["baseline"] = baseline
            return deepcopy(state)

        return self.mutate(apply)

    def reset_baseline(self) -> dict[str, Any]:
        def apply(state: dict[str, Any]) -> dict[str, Any]:
            state["baseline"] = {}
            return deepcopy(state)

        return self.mutate(apply)

    def snapshot(self) -> dict[str, Any]:
        state = self.load()
        return {
            "version": state.get("version", _STATE_VERSION),
            "fact_count": len(state.get("facts") or {}),
            "baseline_fact_count": len(state.get("baseline") or {}),
            "last_candidate_at": state.get("last_candidate_at"),
            "last_observation_at": state.get("last_observation_at"),
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
        payload.setdefault("facts", {})
        payload.setdefault("baseline", {})
        payload.setdefault("last_candidate_at", None)
        payload.setdefault("last_observation_at", None)
        return payload

    def _save_unlocked(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state["version"] = _STATE_VERSION
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
