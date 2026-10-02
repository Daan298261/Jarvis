"""Unforgeable human ApprovalGrant store (RFC-0031).

Only trusted owner channels may create or satisfy a grant. Model/tool arguments
such as confirmed=true can never create or satisfy one.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from ..config import data_dir
from .reversibility import FORGERY_CONFIRMATION_KEYS, model_attempted_self_confirm

Decision = Literal["allow_once", "always", "deny", "approve", "reject"]
OriginChannel = Literal["ui", "api", "voice", "physical", "decision_inbox", "mobile"]

TRUSTED_CHANNELS = frozenset({"ui", "api", "voice", "physical", "decision_inbox", "mobile"})
UNTRUSTED_CHANNELS = frozenset({"model", "tool", "agent", "worker", "inference", ""})

_STORE_FILE = "approval_grants.json"
_PENDING_FILE = "approval_grant_pending.json"
_LOCK = threading.RLock()
_DEFAULT_TTL_SECONDS = 30 * 60
_POLICY_VERSION = "rfc0031-v1"
_MAX_AUDIT = 500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utcnow()).isoformat()


def _store_path() -> Path:
    path = data_dir() / "policy" / _STORE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _pending_path() -> Path:
    path = data_dir() / "policy" / _PENDING_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reset_approval_grants() -> None:
    with _LOCK:
        for path in (_store_path(), _pending_path()):
            if path.exists():
                path.unlink()


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "items": {}, "audit": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "items": {}, "audit": []}
    if not isinstance(raw, dict):
        return {"version": 1, "items": {}, "audit": []}
    items = raw.get("items")
    audit = raw.get("audit")
    if not isinstance(items, dict):
        items = {}
    if not isinstance(audit, list):
        audit = []
    return {"version": 1, "items": items, "audit": audit}


def _save(path: Path, store: dict[str, Any]) -> None:
    audit = list(store.get("audit") or [])
    if len(audit) > _MAX_AUDIT:
        audit = audit[-_MAX_AUDIT:]
    store["audit"] = audit
    path.write_text(json.dumps(store, indent=2, default=str) + "\n", encoding="utf-8")


def _append_audit(store: dict[str, Any], event: dict[str, Any]) -> None:
    row = {"id": uuid.uuid4().hex, "timestamp": _iso(), **event}
    # Never persist secret-looking payloads
    for key in ("arguments", "secrets", "content", "password", "token"):
        row.pop(key, None)
    store.setdefault("audit", []).append(row)


def park_approval_request(
    *,
    action_id: str,
    tool_name: str,
    action: str,
    scope: dict[str, Any],
    target: str,
    task_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    step_key: str | None = None,
    reason: str = "",
    effect: dict[str, Any] | None = None,
    origin_hint: str = "decision_inbox",
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Park a durable approval request without holding the worker loop."""
    pending_id = uuid.uuid4().hex
    expires = _utcnow() + timedelta(seconds=max(60, int(ttl_seconds)))
    row = {
        "id": pending_id,
        "status": "pending",
        "action_id": action_id,
        "tool_name": tool_name,
        "action": action,
        "scope": {
            "tool_name": tool_name,
            "action": action,
            "target": target,
            **{k: v for k, v in (scope or {}).items() if k.lower() not in FORGERY_CONFIRMATION_KEYS},
        },
        "target": target,
        "task_id": task_id,
        "run_id": run_id,
        "step_id": step_id,
        "step_key": step_key,
        "reason": reason[:800],
        "effect": effect or {},
        "origin_hint": origin_hint,
        "created_at": _iso(),
        "expires_at": _iso(expires),
        "policy_version": _POLICY_VERSION,
    }
    with _LOCK:
        store = _load(_pending_path())
        store["items"][pending_id] = row
        _append_audit(
            store,
            {
                "kind": "approval_parked",
                "pending_id": pending_id,
                "action_id": action_id,
                "tool_name": tool_name,
                "task_id": task_id,
                "run_id": run_id,
                "step_id": step_id,
            },
        )
        _save(_pending_path(), store)
    return dict(row)


def list_pending_grants(*, task_id: str | None = None, open_only: bool = True) -> list[dict[str, Any]]:
    with _LOCK:
        store = _load(_pending_path())
        _expire_pending_unlocked(store)
        rows = []
        for item in store["items"].values():
            if open_only and item.get("status") != "pending":
                continue
            if task_id and item.get("task_id") != task_id:
                continue
            rows.append(dict(item))
        rows.sort(key=lambda r: r.get("created_at") or "")
        return rows


def get_pending_grant(pending_id: str) -> dict[str, Any]:
    with _LOCK:
        store = _load(_pending_path())
        _expire_pending_unlocked(store)
        row = store["items"].get((pending_id or "").strip())
        if not row:
            raise KeyError(pending_id)
        return dict(row)


def _expire_pending_unlocked(store: dict[str, Any]) -> None:
    now = _utcnow()
    changed = False
    for row in store["items"].values():
        if row.get("status") != "pending":
            continue
        expires_at = row.get("expires_at") or ""
        try:
            exp = datetime.fromisoformat(expires_at)
        except ValueError:
            continue
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            row["status"] = "timeout"
            row["decided_at"] = _iso()
            row["decision"] = "timeout"
            _append_audit(
                store,
                {
                    "kind": "approval_timeout",
                    "pending_id": row.get("id"),
                    "action_id": row.get("action_id"),
                    "task_id": row.get("task_id"),
                },
            )
            changed = True
    if changed:
        _save(_pending_path(), store)


def decide_approval_request(
    pending_id: str,
    *,
    decision: str,
    origin_channel: str,
    actor: str,
    session_id: str | None = None,
    owner_note: str | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Create an ApprovalGrant (or rejection) from a trusted human channel only."""
    channel = (origin_channel or "").strip().lower()
    if channel in UNTRUSTED_CHANNELS or channel not in TRUSTED_CHANNELS:
        raise PermissionError(
            f"origin_channel={origin_channel!r} cannot create an ApprovalGrant; "
            "only trusted owner channels may satisfy a human gate"
        )
    if model_attempted_self_confirm({"confirmed": True}):  # sanity: forgery helper exists
        pass
    actor_name = (actor or "").strip()
    if not actor_name:
        raise PermissionError("actor is required for ApprovalGrant")

    normalized = (decision or "").strip().lower()
    if normalized in {"allow_once", "always", "approve", "allow", "yes"}:
        grant_decision: Decision = "allow_once" if normalized != "always" else "always"
        approved = True
    elif normalized in {"deny", "reject", "no"}:
        grant_decision = "deny"
        approved = False
    else:
        raise ValueError(f"unsupported decision: {decision}")

    with _LOCK:
        pending_store = _load(_pending_path())
        _expire_pending_unlocked(pending_store)
        row = pending_store["items"].get((pending_id or "").strip())
        if not row:
            raise KeyError(pending_id)
        if row.get("status") == "timeout":
            raise TimeoutError("approval request timed out")
        if row.get("status") != "pending":
            raise ValueError(f"approval request already {row.get('status')}")

        row = dict(row)
        row["status"] = "approved" if approved else "rejected"
        row["decision"] = grant_decision
        row["decided_at"] = _iso()
        row["actor"] = actor_name
        row["origin_channel"] = channel
        row["session_id"] = session_id or ""
        row["owner_note"] = (owner_note or "")[:500]
        pending_store["items"][row["id"]] = row
        _append_audit(
            pending_store,
            {
                "kind": "approval_decided",
                "pending_id": row["id"],
                "decision": grant_decision,
                "origin_channel": channel,
                "actor": actor_name,
                "action_id": row.get("action_id"),
                "task_id": row.get("task_id"),
            },
        )
        _save(_pending_path(), pending_store)

        if not approved:
            return {
                "status": "rejected",
                "pending_id": row["id"],
                "decision": grant_decision,
                "grant": None,
                "task_id": row.get("task_id"),
                "run_id": row.get("run_id"),
                "step_id": row.get("step_id"),
                "step_key": row.get("step_key"),
            }

        grant_id = uuid.uuid4().hex
        expires = _utcnow() + timedelta(seconds=max(60, int(ttl_seconds)))
        grant = {
            "id": grant_id,
            "pending_id": row["id"],
            "action_id": row["action_id"],
            "tool_name": row["tool_name"],
            "action": row.get("action") or "",
            "scope": dict(row.get("scope") or {}),
            "target": row.get("target") or "",
            "origin_channel": channel,
            "actor": actor_name,
            "session_id": session_id or "",
            "timestamp": _iso(),
            "expires_at": _iso(expires),
            "policy_version": _POLICY_VERSION,
            "decision": grant_decision,
            "consumed": False,
            "task_id": row.get("task_id"),
            "run_id": row.get("run_id"),
            "step_id": row.get("step_id"),
            "step_key": row.get("step_key"),
            "owner_note": row.get("owner_note") or "",
        }
        grants = _load(_store_path())
        grants["items"][grant_id] = grant
        _append_audit(
            grants,
            {
                "kind": "grant_created",
                "grant_id": grant_id,
                "pending_id": row["id"],
                "action_id": grant["action_id"],
                "origin_channel": channel,
                "actor": actor_name,
                "decision": grant_decision,
            },
        )
        _save(_store_path(), grants)
        return {
            "status": "approved",
            "pending_id": row["id"],
            "decision": grant_decision,
            "grant": dict(grant),
            "task_id": row.get("task_id"),
            "run_id": row.get("run_id"),
            "step_id": row.get("step_id"),
            "step_key": row.get("step_key"),
        }


def validate_grant_for_action(
    grant_id: str | None,
    *,
    action_id: str,
    tool_name: str,
    target: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return grant if it exactly matches action/scope and is unexpired/unconsumed.

    Model confirmation args never satisfy this check.
    """
    if model_attempted_self_confirm(arguments):
        # Explicitly ignored — cannot satisfy.
        pass
    if not grant_id:
        return None
    with _LOCK:
        store = _load(_store_path())
        grant = store["items"].get(str(grant_id).strip())
        if not grant or grant.get("consumed"):
            return None
        if grant.get("decision") not in {"allow_once", "always", "approve"}:
            return None
        try:
            exp = datetime.fromisoformat(str(grant.get("expires_at") or ""))
        except ValueError:
            return None
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= _utcnow():
            return None
        if grant.get("action_id") != action_id:
            return None
        if grant.get("tool_name") != tool_name:
            return None
        grant_target = str(grant.get("target") or "")
        if grant_target and target and grant_target != target:
            return None
        if grant.get("origin_channel") not in TRUSTED_CHANNELS:
            return None
        return dict(grant)


def consume_grant(grant_id: str) -> dict[str, Any]:
    """Consume a single-use grant. Durable ``always`` grants are left reusable."""
    with _LOCK:
        store = _load(_store_path())
        grant = store["items"].get(str(grant_id).strip())
        if not grant:
            raise KeyError(grant_id)
        grant = dict(grant)
        decision = str(grant.get("decision") or "").strip().lower()
        if decision == "always":
            _append_audit(
                store,
                {
                    "kind": "grant_reuse_always",
                    "grant_id": grant["id"],
                    "action_id": grant.get("action_id"),
                    "tool_name": grant.get("tool_name"),
                    "decision": "always",
                },
            )
            _save(_store_path(), store)
            return grant
        grant["consumed"] = True
        grant["consumed_at"] = _iso()
        store["items"][grant["id"]] = grant
        _append_audit(
            store,
            {
                "kind": "grant_consumed",
                "grant_id": grant["id"],
                "action_id": grant.get("action_id"),
                "tool_name": grant.get("tool_name"),
                "decision": decision or "allow_once",
            },
        )
        _save(_store_path(), store)
        return grant


def reject_timeout_pending(pending_id: str) -> dict[str, Any]:
    """Mark a pending request timed out (test/API helper)."""
    with _LOCK:
        store = _load(_pending_path())
        row = store["items"].get((pending_id or "").strip())
        if not row:
            raise KeyError(pending_id)
        row = dict(row)
        row["status"] = "timeout"
        row["decision"] = "timeout"
        row["decided_at"] = _iso()
        store["items"][row["id"]] = row
        _append_audit(
            store,
            {"kind": "approval_timeout", "pending_id": row["id"], "action_id": row.get("action_id")},
        )
        _save(_pending_path(), store)
        return row


def list_grant_audit(*, limit: int = 100) -> list[dict[str, Any]]:
    with _LOCK:
        grants = _load(_store_path())
        pending = _load(_pending_path())
        events = list(grants.get("audit") or []) + list(pending.get("audit") or [])
    events.sort(key=lambda e: e.get("timestamp") or "")
    return events[-limit:]


def action_id_for(tool_name: str, action: str, target: str, *, task_id: str | None = None) -> str:
    basis = f"{tool_name}|{action}|{target}|{task_id or ''}"
    return uuid.uuid5(uuid.NAMESPACE_URL, basis).hex
