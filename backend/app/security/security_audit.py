"""RFC-0197 security-agent audit log (target registry + denied invokes)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir

_LOCK = threading.RLock()
_AUDIT_NAME = "security-audit.jsonl"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def audit_path() -> Path:
    path = data_dir() / _AUDIT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def audit_security_event(event: str, **fields: Any) -> None:
    """Append one JSON line to data_dir()/security-audit.jsonl."""
    record = {"at": _utcnow(), "event": str(event), **fields}
    with _LOCK:
        with audit_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def read_audit_lines(*, limit: int = 200) -> list[dict[str, Any]]:
    path = audit_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows[-max(1, int(limit or 200)) :]
