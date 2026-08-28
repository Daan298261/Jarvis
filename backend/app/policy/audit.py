from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir

_lock = threading.RLock()
AUDIT_FILE = "audit.jsonl"


def policy_root() -> Path:
    path = data_dir() / "policy"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _audit_path() -> Path:
    return policy_root() / AUDIT_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_policy_change(
    *,
    actor: str,
    profile_id: str | None,
    field: str,
    old_value: Any,
    new_value: Any,
) -> dict[str, Any]:
    event = {
        "id": str(uuid.uuid4()),
        "actor": actor or "system",
        "profile_id": profile_id,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "timestamp": _utc_now(),
    }
    with _lock:
        with _audit_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str) + "\n")
    return event


def list_audit_events(*, profile_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
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
        except Exception:
            continue
        if profile_id and event.get("profile_id") != profile_id:
            continue
        events.append(event)
        if len(events) >= limit:
            break
    return events


def reset_audit_log() -> None:
    with _lock:
        path = _audit_path()
        if path.exists():
            path.unlink()
