"""Owner-inspectable Jev / fallback decision log (RFC-0116). Not chat chrome."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from .. import config as app_config

_LOCK = threading.Lock()
_MAX_EVENTS = 80
_AUDIT_NAME = "decision/jev_audit.json"


def _path():
    path = app_config.data_dir() / _AUDIT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_event(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = {
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    with _LOCK:
        events = list_events()
        events.insert(0, event)
        _path().write_text(json.dumps({"events": events[:_MAX_EVENTS]}, indent=2) + "\n", encoding="utf-8")
    return event


def list_events(limit: int = 40) -> list[dict[str, Any]]:
    target = _path()
    if not target.is_file():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return []
    cleaned = [item for item in events if isinstance(item, dict)]
    cap = max(1, min(int(limit or 40), _MAX_EVENTS))
    return cleaned[:cap]


def reset_audit() -> None:
    with _LOCK:
        target = _path()
        if target.is_file():
            target.unlink()
