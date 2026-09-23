from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir

_lock = threading.RLock()
AUDIT_NAME = "audit.jsonl"


def _root() -> Path:
    path = data_dir() / "automation-breaker"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _audit_path() -> Path:
    return _root() / AUDIT_NAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_breaker_audit(
    *,
    event_type: str,
    automation_id: str,
    actor: str = "system",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "id": str(uuid.uuid4()),
        "event_type": event_type,
        "automation_id": automation_id,
        "actor": actor or "system",
        "timestamp": _utc_now(),
        "detail": dict(detail or {}),
    }
    with _lock:
        with _audit_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str) + "\n")
    return event


def list_breaker_audit(
    *,
    automation_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    path = _audit_path()
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with _lock:
        lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if automation_id and event.get("automation_id") != automation_id:
            continue
        events.append(event)
        if len(events) >= limit:
            break
    return events


def reset_breaker_audit() -> None:
    with _lock:
        path = _audit_path()
        if path.exists():
            path.unlink()
