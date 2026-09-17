"""Parked owner approvals for side-effecting API actions (RFC-0110 backend path)."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .computer_permissions import (
    apply_grant,
    describe_permission,
    evaluate_permission,
    get_spec,
    spoken_prompt_for_permission,
)

_STORE_FILE = "approval-pending.json"
_LOCK = threading.RLock()
_OWNER_NOTE_MAX = 500

# RFC-0110 modal choices (no silent session auto-grant on API paths).
DECISION_MODES = frozenset({"allow_once", "always", "deny"})
RESPONSE_OPTIONS = ("allow_once", "always", "deny")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def pending_store_path() -> Path:
    path = data_dir() / _STORE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reset_pending_approval_state() -> None:
    with _LOCK:
        if pending_store_path().exists():
            pending_store_path().unlink()


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "pending": {}}


def _load_unlocked() -> dict[str, Any]:
    path = pending_store_path()
    if not path.exists():
        return _empty_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    pending = raw.get("pending")
    if not isinstance(pending, dict):
        pending = {}
    return {"version": 1, "pending": pending}


def _save_unlocked(store: dict[str, Any]) -> None:
    pending_store_path().write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def _normalize_owner_note(note: str | None) -> str:
    cleaned = (note or "").strip()
    if len(cleaned) > _OWNER_NOTE_MAX:
        return cleaned[:_OWNER_NOTE_MAX]
    return cleaned


def list_pending_approvals() -> list[dict[str, Any]]:
    with _LOCK:
        store = _load_unlocked()
        rows = [dict(item) for item in store["pending"].values() if item.get("status") == "pending"]
    rows.sort(key=lambda item: item.get("created_at") or "")
    return rows


def get_pending(pending_id: str) -> dict[str, Any]:
    ident = (pending_id or "").strip()
    with _LOCK:
        store = _load_unlocked()
        row = store["pending"].get(ident)
    if not row or row.get("status") != "pending":
        raise KeyError(pending_id)
    return dict(row)


def park_action(
    *,
    action_kind: str,
    permission_ids: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not permission_ids:
        raise ValueError("permission_ids is required")
    primary = permission_ids[0]
    spec = get_spec(primary)
    pending_ids = [item for item in permission_ids if evaluate_permission(item).status == "ask"]
    if not pending_ids:
        raise ValueError("no permissions are waiting for approval")
    pending_id = uuid.uuid4().hex
    row = {
        "id": pending_id,
        "status": "pending",
        "action_kind": action_kind,
        "permission_id": primary,
        "permission_ids": pending_ids,
        "context": context or {},
        "created_at": _utcnow(),
        "owner_note": "",
    }
    with _LOCK:
        store = _load_unlocked()
        store["pending"][pending_id] = row
        _save_unlocked(store)
    return pending_response(row, spec=spec)


def pending_response(row: dict[str, Any], *, spec=None) -> dict[str, Any]:
    primary = str(row.get("permission_id") or "")
    if spec is None:
        spec = get_spec(primary)
    permission_ids = list(row.get("permission_ids") or [primary])
    return {
        "status": "pending_approval",
        "pending_id": row["id"],
        "kind": "permission",
        "action_kind": row.get("action_kind"),
        "permission_id": primary,
        "permission_ids": permission_ids,
        "pending": permission_ids,
        "title": spec.title,
        "detail": spec.detail,
        "reason": evaluate_permission(primary).reason,
        "options": list(RESPONSE_OPTIONS),
        "catalog": [describe_permission(item) for item in permission_ids],
        "spoken_prompt": spoken_prompt_for_permission(primary, permission_ids),
        "voice_reply_hint": "Say allow this time, always allow, or deny.",
        "context": dict(row.get("context") or {}),
        "created_at": row.get("created_at"),
    }


def decide_pending(
    pending_id: str,
    mode: str,
    *,
    owner_note: str | None = None,
) -> dict[str, Any]:
    normalized = str(mode or "").strip().lower()
    if normalized not in DECISION_MODES:
        raise ValueError(f"unsupported decision mode: {mode}")
    note = _normalize_owner_note(owner_note)
    with _LOCK:
        store = _load_unlocked()
        row = store["pending"].get((pending_id or "").strip())
        if not row or row.get("status") != "pending":
            raise KeyError(pending_id)
        row = dict(row)
        row["owner_note"] = note
        row["decided_at"] = _utcnow()
        row["decision"] = normalized
        if normalized == "deny":
            row["status"] = "denied"
            store["pending"][row["id"]] = row
            _save_unlocked(store)
            return {
                "status": "denied",
                "pending_id": row["id"],
                "action_kind": row.get("action_kind"),
                "owner_note": note,
                "executed": False,
            }
        permission_ids = list(row.get("permission_ids") or [row.get("permission_id")])
        grants: list[dict[str, Any]] = []
        for permission_id in permission_ids:
            grants.append(apply_grant(str(permission_id), normalized, persist=normalized in {"always", "deny", "ask"}))
        row["status"] = "approved"
        store["pending"][row["id"]] = row
        _save_unlocked(store)
    return {
        "status": "approved",
        "pending_id": row["id"],
        "action_kind": row.get("action_kind"),
        "decision": normalized,
        "owner_note": note,
        "grants": grants,
        "permission_ids": permission_ids,
        "context": dict(row.get("context") or {}),
        "executed": False,
    }
