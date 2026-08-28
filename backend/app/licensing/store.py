from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cluster import licensing_root

_lock = threading.RLock()
STATE_FILE = "state.json"
INFERENCE_CREDENTIALS_FILE = "inference_credentials.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _state_path() -> Path:
    return licensing_root() / STATE_FILE


def _inference_credentials_path() -> Path:
    return licensing_root() / INFERENCE_CREDENTIALS_FILE


def _empty_state() -> dict[str, Any]:
    return {
        "lease": None,
        "last_validated_at": None,
        "last_status": "unlicensed",
        "last_message": "No active platform lease",
    }


def reset_licensing_store() -> None:
    with _lock:
        for path in (_state_path(), _inference_credentials_path()):
            if path.exists():
                path.unlink()


def load_state() -> dict[str, Any]:
    with _lock:
        path = _state_path()
        if not path.exists():
            return _empty_state()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return _empty_state()
        if not isinstance(raw, dict):
            return _empty_state()
        state = _empty_state()
        state.update(raw)
        return state


def save_state(state: dict[str, Any]) -> None:
    with _lock:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def set_lease(lease: dict[str, Any] | None) -> dict[str, Any]:
    with _lock:
        state = load_state()
        state["lease"] = lease
        save_state(state)
        return state


def update_validation_state(
    *,
    status: str,
    message: str,
    validated_at: str | None = None,
) -> dict[str, Any]:
    with _lock:
        state = load_state()
        state["last_status"] = status
        state["last_message"] = message
        if validated_at is not None:
            state["last_validated_at"] = validated_at
        save_state(state)
        return state


def _empty_inference_store() -> dict[str, Any]:
    return {"credentials": []}


def load_inference_credentials() -> dict[str, Any]:
    with _lock:
        path = _inference_credentials_path()
        if not path.exists():
            return _empty_inference_store()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return _empty_inference_store()
        if not isinstance(raw, dict):
            return _empty_inference_store()
        if not isinstance(raw.get("credentials"), list):
            raw["credentials"] = []
        return raw


def save_inference_credentials(payload: dict[str, Any]) -> None:
    with _lock:
        path = _inference_credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def new_record_timestamp() -> str:
    return _utc_now()
