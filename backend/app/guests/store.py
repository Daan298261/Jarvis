from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .schema import PortalRecord, PortalScope, PortalLimits, PortalSession, scope_from_dict

_lock = threading.RLock()
STATE_FILE = "state.json"
AUDIT_FILE = "audit.jsonl"


def guests_root() -> Path:
    path = data_dir() / "guest-portals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return guests_root() / STATE_FILE


def _audit_path() -> Path:
    return guests_root() / AUDIT_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty_state() -> dict[str, Any]:
    return {"portals": {}}


def reset_guest_store() -> None:
    with _lock:
        root = guests_root()
        for name in (STATE_FILE, AUDIT_FILE):
            path = root / name
            if path.exists():
                path.unlink()


def _load_state_unlocked() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()
    if not isinstance(raw, dict):
        return _empty_state()
    raw.setdefault("portals", {})
    return raw


def _save_state_unlocked(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _portal_from_dict(raw: dict[str, Any]) -> PortalRecord:
    limits_raw = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
    sessions_raw = raw.get("sessions") if isinstance(raw.get("sessions"), list) else []
    sessions = [
        PortalSession(
            session_id=str(item.get("session_id")),
            guest_label=str(item.get("guest_label") or ""),
            created_at=str(item.get("created_at") or ""),
            last_seen_at=str(item.get("last_seen_at") or ""),
        )
        for item in sessions_raw
        if isinstance(item, dict) and item.get("session_id")
    ]
    return PortalRecord(
        id=str(raw.get("id")),
        label=str(raw.get("label") or ""),
        guest_label=str(raw.get("guest_label") or ""),
        scope=scope_from_dict(raw.get("scope") if isinstance(raw.get("scope"), dict) else None),
        limits=PortalLimits(
            single_use=bool(limits_raw.get("single_use")),
            max_sessions=limits_raw.get("max_sessions"),
            max_uses=limits_raw.get("max_uses"),
        ),
        token_hash=str(raw.get("token_hash") or ""),
        created_at=str(raw.get("created_at") or ""),
        expires_at=raw.get("expires_at"),
        revoked=bool(raw.get("revoked")),
        revoked_at=raw.get("revoked_at"),
        uses_remaining=raw.get("uses_remaining"),
        sessions=sessions,
    )


def _portal_to_dict(portal: PortalRecord) -> dict[str, Any]:
    return {
        "id": portal.id,
        "label": portal.label,
        "guest_label": portal.guest_label,
        "scope": portal.scope.model_dump(),
        "limits": portal.limits.model_dump(),
        "token_hash": portal.token_hash,
        "created_at": portal.created_at,
        "expires_at": portal.expires_at,
        "revoked": portal.revoked,
        "revoked_at": portal.revoked_at,
        "uses_remaining": portal.uses_remaining,
        "sessions": [session.model_dump() for session in portal.sessions],
    }


def list_portals() -> list[PortalRecord]:
    with _lock:
        state = _load_state_unlocked()
        portals = state.get("portals", {})
        return [_portal_from_dict(item) for item in portals.values() if isinstance(item, dict)]


def get_portal(portal_id: str) -> PortalRecord | None:
    with _lock:
        state = _load_state_unlocked()
        raw = state.get("portals", {}).get(portal_id)
        if not isinstance(raw, dict):
            return None
        return _portal_from_dict(raw)


def get_portal_by_token_hash(token_hash: str) -> PortalRecord | None:
    with _lock:
        state = _load_state_unlocked()
        for raw in state.get("portals", {}).values():
            if isinstance(raw, dict) and raw.get("token_hash") == token_hash:
                return _portal_from_dict(raw)
        return None


def save_portal(portal: PortalRecord) -> PortalRecord:
    with _lock:
        state = _load_state_unlocked()
        portals = state.setdefault("portals", {})
        portals[portal.id] = _portal_to_dict(portal)
        _save_state_unlocked(state)
        return portal


def append_audit(entry: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        path = _audit_path()
        payload = dict(entry)
        payload.setdefault("id", str(uuid.uuid4()))
        payload.setdefault("created_at", _utc_now())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return payload


def list_audit(portal_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with _lock:
        path = _audit_path()
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if portal_id and item.get("portal_id") != portal_id:
                continue
            rows.append(item)
        return rows[-limit:]
