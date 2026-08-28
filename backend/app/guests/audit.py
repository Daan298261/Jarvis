from __future__ import annotations

from typing import Any

from .store import append_audit


def record_audit(
    *,
    portal_id: str,
    session_id: str,
    guest_label: str,
    action: str,
    outcome: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    path: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    return append_audit(
        {
            "portal_id": portal_id,
            "session_id": session_id,
            "guest_label": guest_label,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "path": path,
            "outcome": outcome,
            "detail": detail,
        }
    )
