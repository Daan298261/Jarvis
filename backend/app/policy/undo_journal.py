"""Durable undo / compensation journal for RFC-0031.

Linked to task/run/step IDs. Bounded history. No unbounded secret blobs.
Composite actions retain per-child records and reverse in safe reverse order.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import data_dir

_STORE_FILE = "undo_journal.json"
_LOCK = threading.RLock()
_DEFAULT_MAX_RECORDS = 200
_MAX_STATE_CHARS = 4000
_SECRET_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "private_key",
        "content",
        "raw",
        "blob",
    }
)
# Restore references must survive journal redaction (payloads live on disk).
_RESTORE_SAFE_KEYS = frozenset(
    {
        "kind",
        "path",
        "existed",
        "was_directory",
        "snapshot_path",
        "sha256",
        "encoding",
        "size",
        "key",
        "previous_value",
        "restorable",
        "tool_name",
        "action",
        "target",
    }
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path() -> Path:
    path = data_dir() / "policy" / _STORE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reset_undo_journal() -> None:
    with _LOCK:
        if _path().exists():
            _path().unlink()


def _load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {"version": 1, "max_records": _DEFAULT_MAX_RECORDS, "records": [], "audit": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "max_records": _DEFAULT_MAX_RECORDS, "records": [], "audit": []}
    if not isinstance(raw, dict):
        return {"version": 1, "max_records": _DEFAULT_MAX_RECORDS, "records": [], "audit": []}
    records = raw.get("records")
    audit = raw.get("audit")
    if not isinstance(records, list):
        records = []
    if not isinstance(audit, list):
        audit = []
    max_records = int(raw.get("max_records") or _DEFAULT_MAX_RECORDS)
    return {"version": 1, "max_records": max_records, "records": records, "audit": audit}


def _save(store: dict[str, Any]) -> None:
    max_records = int(store.get("max_records") or _DEFAULT_MAX_RECORDS)
    records = list(store.get("records") or [])
    if len(records) > max_records:
        records = records[-max_records:]
    store["records"] = records
    audit = list(store.get("audit") or [])
    if len(audit) > 500:
        audit = audit[-500:]
    store["audit"] = audit
    _path().write_text(json.dumps(store, indent=2, default=str) + "\n", encoding="utf-8")


def _redact_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in state.items():
        lowered = str(key).lower()
        if lowered in _RESTORE_SAFE_KEYS:
            # Keep restore references / small settings previous_value for apply_undo.
            if lowered == "previous_value" and isinstance(value, str) and len(value) > _MAX_STATE_CHARS:
                out[key] = {
                    "ref": True,
                    "sha256": hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest(),
                    "chars": len(value),
                    "preview": value[:120] + "…",
                }
            else:
                out[key] = value
            continue
        if lowered in _SECRET_KEYS or any(part in lowered for part in ("password", "secret", "token")):
            out[key] = {"redacted": True, "kind": "secret"}
            continue
        if isinstance(value, str) and len(value) > _MAX_STATE_CHARS:
            digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
            out[key] = {
                "ref": True,
                "sha256": digest,
                "chars": len(value),
                "preview": value[:120] + "…",
            }
        elif isinstance(value, (bytes, bytearray)):
            out[key] = {"ref": True, "bytes": len(value), "sha256": hashlib.sha256(bytes(value)).hexdigest()}
        else:
            out[key] = value
    return out


def configure_undo_bound(max_records: int) -> None:
    with _LOCK:
        store = _load()
        store["max_records"] = max(1, int(max_records))
        _save(store)


def register_undo_record(
    *,
    tool_name: str,
    action: str,
    target: str,
    reversibility: str,
    undo_operation: str,
    preconditions: list[str],
    prior_state: dict[str, Any] | None = None,
    post_state: dict[str, Any] | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    step_key: str | None = None,
    parent_id: str | None = None,
    child_ids: list[str] | None = None,
    compensation_has_external_effects: bool = False,
    summary: str = "",
) -> dict[str, Any]:
    record = {
        "id": uuid.uuid4().hex,
        "created_at": _utcnow(),
        "status": "ready",
        "tool_name": tool_name,
        "action": action,
        "target": target,
        "reversibility": reversibility,
        "undo_operation": undo_operation,
        "preconditions": list(preconditions or []),
        "prior_state": _redact_state(prior_state),
        "post_state": _redact_state(post_state),
        "task_id": task_id,
        "run_id": run_id,
        "step_id": step_id,
        "step_key": step_key,
        "parent_id": parent_id,
        "child_ids": list(child_ids or []),
        "compensation_has_external_effects": bool(compensation_has_external_effects),
        "summary": (summary or f"Undo {tool_name}.{action} on {target}")[:500],
        "undone_at": None,
        "conflict": None,
    }
    with _LOCK:
        store = _load()
        store["records"].append(record)
        store["audit"].append(
            {
                "id": uuid.uuid4().hex,
                "timestamp": _utcnow(),
                "kind": "undo_registered",
                "record_id": record["id"],
                "tool_name": tool_name,
                "action": action,
                "task_id": task_id,
                "run_id": run_id,
                "step_id": step_id,
                "reversibility": reversibility,
            }
        )
        _save(store)
    return dict(record)


def register_composite_undo(
    *,
    tool_name: str,
    action: str,
    target: str,
    children: list[dict[str, Any]],
    task_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    step_key: str | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """Register a parent composite plus per-child recovery records."""
    parent_id = uuid.uuid4().hex
    child_ids: list[str] = []
    with _LOCK:
        store = _load()
        for child in children:
            child_id = uuid.uuid4().hex
            child_ids.append(child_id)
            store["records"].append(
                {
                    "id": child_id,
                    "created_at": _utcnow(),
                    "status": "ready",
                    "tool_name": str(child.get("tool_name") or tool_name),
                    "action": str(child.get("action") or action),
                    "target": str(child.get("target") or ""),
                    "reversibility": str(child.get("reversibility") or "REVERSIBLE"),
                    "undo_operation": str(child.get("undo_operation") or "restore_prior"),
                    "preconditions": list(child.get("preconditions") or ["post_state_matches"]),
                    "prior_state": _redact_state(child.get("prior_state")),
                    "post_state": _redact_state(child.get("post_state")),
                    "task_id": task_id,
                    "run_id": run_id,
                    "step_id": step_id,
                    "step_key": step_key,
                    "parent_id": parent_id,
                    "child_ids": [],
                    "compensation_has_external_effects": bool(
                        child.get("compensation_has_external_effects") or False
                    ),
                    "summary": str(child.get("summary") or "")[:500],
                    "undone_at": None,
                    "conflict": None,
                    "composite_order": int(child.get("order") or len(child_ids)),
                }
            )
        parent = {
            "id": parent_id,
            "created_at": _utcnow(),
            "status": "ready",
            "tool_name": tool_name,
            "action": action,
            "target": target,
            "reversibility": "REVERSIBLE",
            "undo_operation": "composite_reverse_children",
            "preconditions": ["all_ready_children_safe"],
            "prior_state": {},
            "post_state": {"child_count": len(child_ids)},
            "task_id": task_id,
            "run_id": run_id,
            "step_id": step_id,
            "step_key": step_key,
            "parent_id": None,
            "child_ids": child_ids,
            "compensation_has_external_effects": False,
            "summary": (summary or f"Composite undo for {tool_name}.{action}")[:500],
            "undone_at": None,
            "conflict": None,
        }
        store["records"].append(parent)
        store["audit"].append(
            {
                "id": uuid.uuid4().hex,
                "timestamp": _utcnow(),
                "kind": "composite_undo_registered",
                "record_id": parent_id,
                "child_ids": child_ids,
                "task_id": task_id,
                "run_id": run_id,
                "step_id": step_id,
            }
        )
        _save(store)
    return dict(parent)


def get_undo_record(record_id: str) -> dict[str, Any]:
    with _LOCK:
        store = _load()
        for row in store["records"]:
            if row.get("id") == record_id:
                return dict(row)
    raise KeyError(record_id)


def list_undo_records(
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    ready_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with _LOCK:
        store = _load()
        rows = [dict(r) for r in store["records"]]
    if task_id:
        rows = [r for r in rows if r.get("task_id") == task_id]
    if run_id:
        rows = [r for r in rows if r.get("run_id") == run_id]
    if ready_only:
        rows = [r for r in rows if r.get("status") == "ready"]
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[: max(1, int(limit))]


def describe_undo(record_id: str) -> dict[str, Any]:
    """Exactly what will reverse — for UI / NL undo preview."""
    record = get_undo_record(record_id)
    children = []
    if record.get("child_ids"):
        with _LOCK:
            store = _load()
            by_id = {r["id"]: r for r in store["records"]}
        ordered = []
        for cid in record["child_ids"]:
            child = by_id.get(cid)
            if child:
                ordered.append(child)
        # Preview reverse order (safe rollback order)
        for child in reversed(ordered):
            children.append(
                {
                    "id": child["id"],
                    "undo_operation": child.get("undo_operation"),
                    "target": child.get("target"),
                    "summary": child.get("summary"),
                    "status": child.get("status"),
                }
            )
    return {
        "id": record["id"],
        "summary": record.get("summary"),
        "undo_operation": record.get("undo_operation"),
        "target": record.get("target"),
        "tool_name": record.get("tool_name"),
        "action": record.get("action"),
        "preconditions": list(record.get("preconditions") or []),
        "reversibility": record.get("reversibility"),
        "task_id": record.get("task_id"),
        "run_id": record.get("run_id"),
        "step_id": record.get("step_id"),
        "status": record.get("status"),
        "children_reverse_order": children,
        "will_reverse": (
            f"{record.get('undo_operation')} on {record.get('target')}"
            if not children
            else f"composite reverse {len(children)} children in reverse dependency order"
        ),
    }


def _precondition_ok(
    record: dict[str, Any],
    *,
    world_checker: Callable[[dict[str, Any]], tuple[bool, str]] | None = None,
) -> tuple[bool, str]:
    if record.get("status") != "ready":
        return False, f"record status is {record.get('status')}"
    post = record.get("post_state") or {}
    if post.get("stale") is True:
        return False, "postcondition marked stale; world changed since action"
    if "expected_digest" in post and "current_digest" in post:
        if post["expected_digest"] != post["current_digest"]:
            return False, "current digest diverges from expected postcondition"
    if world_checker is not None:
        ok, reason = world_checker(record)
        if not ok:
            return False, reason
    return True, "ok"


def apply_undo(
    record_id: str,
    *,
    world_checker: Callable[[dict[str, Any]], tuple[bool, str]] | None = None,
    executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-validate preconditions and apply undo; never mark undone without reverse.

    When ``executor`` is omitted, the default restore executor runs. Missing reverse
    payloads yield ``not_implemented`` (record stays ``ready``). Unsafe world state
    yields ``conflict``.
    """
    from .undo_restore import UndoConflictError, UndoNotImplementedError, default_undo_executor

    run_exec = executor or default_undo_executor

    with _LOCK:
        store = _load()
        by_id = {r["id"]: r for r in store["records"]}
        record = by_id.get(record_id)
        if not record:
            raise KeyError(record_id)

        # Composite: reverse completed children in reverse order
        if record.get("child_ids"):
            child_rows = [by_id[cid] for cid in record["child_ids"] if cid in by_id]
            child_rows.sort(key=lambda r: int(r.get("composite_order") or 0), reverse=True)
            results = []
            for child in child_rows:
                if child.get("status") != "ready":
                    continue
                ok, reason = _precondition_ok(child, world_checker=world_checker)
                if not ok:
                    child["status"] = "conflict"
                    child["conflict"] = reason
                    results.append({"id": child["id"], "status": "conflict", "reason": reason})
                    record["status"] = "conflict"
                    record["conflict"] = f"child {child['id']}: {reason}"
                    store["audit"].append(
                        {
                            "id": uuid.uuid4().hex,
                            "timestamp": _utcnow(),
                            "kind": "undo_conflict",
                            "record_id": record_id,
                            "child_id": child["id"],
                            "reason": reason,
                        }
                    )
                    _save(store)
                    return {
                        "status": "conflict",
                        "record_id": record_id,
                        "reason": record["conflict"],
                        "children": results,
                        "preview": describe_undo(record_id),
                    }
                try:
                    run_exec(child)
                except UndoNotImplementedError as exc:
                    store["audit"].append(
                        {
                            "id": uuid.uuid4().hex,
                            "timestamp": _utcnow(),
                            "kind": "undo_not_implemented",
                            "record_id": record_id,
                            "child_id": child["id"],
                            "reason": str(exc),
                        }
                    )
                    _save(store)
                    return {
                        "status": "not_implemented",
                        "record_id": record_id,
                        "reason": str(exc),
                        "children": results,
                        "preview": describe_undo(record_id),
                    }
                except UndoConflictError as exc:
                    child["status"] = "conflict"
                    child["conflict"] = str(exc)
                    record["status"] = "conflict"
                    record["conflict"] = str(exc)
                    store["audit"].append(
                        {
                            "id": uuid.uuid4().hex,
                            "timestamp": _utcnow(),
                            "kind": "undo_conflict",
                            "record_id": record_id,
                            "child_id": child["id"],
                            "reason": str(exc),
                        }
                    )
                    _save(store)
                    return {
                        "status": "conflict",
                        "record_id": record_id,
                        "reason": str(exc),
                        "children": results,
                        "preview": describe_undo(record_id),
                    }
                child["status"] = "undone"
                child["undone_at"] = _utcnow()
                results.append({"id": child["id"], "status": "undone", "undo_operation": child.get("undo_operation")})
            record["status"] = "undone"
            record["undone_at"] = _utcnow()
            store["audit"].append(
                {
                    "id": uuid.uuid4().hex,
                    "timestamp": _utcnow(),
                    "kind": "undo_applied",
                    "record_id": record_id,
                    "composite": True,
                    "child_ids": [c["id"] for c in child_rows],
                }
            )
            _save(store)
            return {
                "status": "undone",
                "record_id": record_id,
                "children": results,
                "order": "reverse_dependency",
                "preview": describe_undo(record_id),
            }

        ok, reason = _precondition_ok(record, world_checker=world_checker)
        if not ok:
            record["status"] = "conflict"
            record["conflict"] = reason
            store["audit"].append(
                {
                    "id": uuid.uuid4().hex,
                    "timestamp": _utcnow(),
                    "kind": "undo_conflict",
                    "record_id": record_id,
                    "reason": reason,
                }
            )
            _save(store)
            return {
                "status": "conflict",
                "record_id": record_id,
                "reason": reason,
                "preview": describe_undo(record_id),
            }
        try:
            exec_result = run_exec(record)
        except UndoNotImplementedError as exc:
            store["audit"].append(
                {
                    "id": uuid.uuid4().hex,
                    "timestamp": _utcnow(),
                    "kind": "undo_not_implemented",
                    "record_id": record_id,
                    "reason": str(exc),
                    "undo_operation": record.get("undo_operation"),
                    "target": record.get("target"),
                }
            )
            _save(store)
            return {
                "status": "not_implemented",
                "record_id": record_id,
                "reason": str(exc),
                "preview": describe_undo(record_id),
            }
        except UndoConflictError as exc:
            record["status"] = "conflict"
            record["conflict"] = str(exc)
            store["audit"].append(
                {
                    "id": uuid.uuid4().hex,
                    "timestamp": _utcnow(),
                    "kind": "undo_conflict",
                    "record_id": record_id,
                    "reason": str(exc),
                }
            )
            _save(store)
            return {
                "status": "conflict",
                "record_id": record_id,
                "reason": str(exc),
                "preview": describe_undo(record_id),
            }
        record["status"] = "undone"
        record["undone_at"] = _utcnow()
        store["audit"].append(
            {
                "id": uuid.uuid4().hex,
                "timestamp": _utcnow(),
                "kind": "undo_applied",
                "record_id": record_id,
                "undo_operation": record.get("undo_operation"),
                "target": record.get("target"),
                "detail": (exec_result or {}).get("detail") if isinstance(exec_result, dict) else None,
            }
        )
        _save(store)
        return {
            "status": "undone",
            "record_id": record_id,
            "undo_operation": record.get("undo_operation"),
            "target": record.get("target"),
            "detail": (exec_result or {}).get("detail") if isinstance(exec_result, dict) else None,
            "preview": describe_undo(record_id),
        }


def mark_post_state_stale(record_id: str, *, current_digest: str | None = None) -> dict[str, Any]:
    """Test/helper: mark world changed so undo conflicts."""
    with _LOCK:
        store = _load()
        for row in store["records"]:
            if row.get("id") == record_id:
                post = dict(row.get("post_state") or {})
                post["stale"] = True
                if current_digest is not None:
                    post["current_digest"] = current_digest
                    post.setdefault("expected_digest", post.get("expected_digest") or "prior")
                row["post_state"] = post
                _save(store)
                return dict(row)
    raise KeyError(record_id)


def list_undo_audit(*, limit: int = 100) -> list[dict[str, Any]]:
    with _LOCK:
        store = _load()
        events = list(store.get("audit") or [])
    return events[-limit:]
