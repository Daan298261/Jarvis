from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import data_dir

STATE_FILE = "persona/owner_session.json"


def _state_path() -> Path:
    path = data_dir() / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_owner_session_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_owner_session_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def reset_owner_session_state() -> None:
    path = _state_path()
    if path.exists():
        path.unlink()
