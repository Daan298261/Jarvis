from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .journal import last_committed_seq
from .resources import full_snapshot
from .store import connect
from .types import ALL_RESOURCE_CLASSES, CheckpointTag

CURRENT_SNAPSHOT_SCHEMA = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_snapshot(snapshot: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Deterministic verification — required keys and parseable structure."""
    errors: list[str] = []
    for resource_class in sorted(ALL_RESOURCE_CLASSES):
        block = snapshot.get(resource_class)
        if not isinstance(block, dict):
            errors.append(f"missing or invalid block: {resource_class}")
    details = {
        "schema_version": CURRENT_SNAPSHOT_SCHEMA,
        "resource_classes": sorted(ALL_RESOURCE_CLASSES),
        "errors": errors,
        "ok": not errors,
    }
    return not errors, details


def create_checkpoint(
    *,
    tag: CheckpointTag = CheckpointTag.CANDIDATE,
    notes: str = "",
    actor: str = "system",
) -> dict[str, Any]:
    snapshot = full_snapshot()
    seq = last_committed_seq()
    cp_id = str(uuid.uuid4())
    created_at = _utc_now()
    snap_hash = _snapshot_hash(snapshot)
    conn = connect()
    conn.execute(
        """
        INSERT INTO checkpoints (id, created_at, tag, journal_seq, snapshot_json, snapshot_hash, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (cp_id, created_at, tag.value, seq, json.dumps(snapshot, sort_keys=True), snap_hash, notes),
    )
    conn.close()
    return get_checkpoint(cp_id) or {}


def get_checkpoint(checkpoint_id: str) -> dict[str, Any] | None:
    conn = connect()
    row = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_checkpoint(row)


def _row_to_checkpoint(row) -> dict[str, Any]:
    verification = None
    if row["verification_json"]:
        try:
            verification = json.loads(row["verification_json"])
        except json.JSONDecodeError:
            verification = {"parse_error": True}
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "tag": row["tag"],
        "journal_seq": row["journal_seq"],
        "snapshot_hash": row["snapshot_hash"],
        "verification": verification,
        "verified_at": row["verified_at"],
        "notes": row["notes"],
        "journal_coverage_seq": row["journal_seq"],
    }


def list_checkpoints(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM checkpoints ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_checkpoint(row) for row in rows]


def verify_and_promote_checkpoint(checkpoint_id: str, *, actor: str = "operator") -> dict[str, Any]:
    cp = get_checkpoint(checkpoint_id)
    if not cp:
        raise KeyError(f"checkpoint not found: {checkpoint_id}")
    conn = connect()
    row = conn.execute("SELECT snapshot_json, snapshot_hash FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    conn.close()
    if not row:
        raise KeyError(checkpoint_id)
    snapshot = json.loads(row["snapshot_json"])
    if _snapshot_hash(snapshot) != row["snapshot_hash"]:
        _set_tag(checkpoint_id, CheckpointTag.INVALID, verification={"ok": False, "reason": "hash_mismatch"})
        raise ValueError("checkpoint snapshot hash mismatch — marked INVALID")
    ok, details = verify_snapshot(snapshot)
    details["actor"] = actor
    if not ok:
        _set_tag(checkpoint_id, CheckpointTag.INVALID, verification=details)
        raise ValueError("checkpoint verification failed")
    _set_tag(checkpoint_id, CheckpointTag.KNOWN_GOOD, verification=details)
    return get_checkpoint(checkpoint_id) or {}


def _set_tag(checkpoint_id: str, tag: CheckpointTag, verification: dict[str, Any] | None = None) -> None:
    conn = connect()
    conn.execute(
        """
        UPDATE checkpoints SET tag = ?, verification_json = ?, verified_at = ?
        WHERE id = ?
        """,
        (
            tag.value,
            json.dumps(verification or {}, sort_keys=True),
            _utc_now() if tag in {CheckpointTag.KNOWN_GOOD, CheckpointTag.INVALID} else None,
            checkpoint_id,
        ),
    )
    conn.close()


def last_known_good_checkpoint() -> dict[str, Any] | None:
    conn = connect()
    row = conn.execute(
        "SELECT * FROM checkpoints WHERE tag = ? ORDER BY journal_seq DESC LIMIT 1",
        (CheckpointTag.KNOWN_GOOD.value,),
    ).fetchone()
    conn.close()
    return _row_to_checkpoint(row) if row else None


def load_checkpoint_snapshot(checkpoint_id: str) -> dict[str, Any]:
    conn = connect()
    row = conn.execute("SELECT snapshot_json FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    conn.close()
    if not row:
        raise KeyError(checkpoint_id)
    return json.loads(row["snapshot_json"])


def operator_summary() -> dict[str, Any]:
    checkpoints = list_checkpoints(limit=100)
    last_good = last_known_good_checkpoint()
    last_recovery = _last_successful_rollback()
    return {
        "checkpoints": [
            {
                "id": item["id"],
                "created_at": item["created_at"],
                "age_seconds": _age_seconds(item["created_at"]),
                "tag": item["tag"],
                "journal_coverage_seq": item["journal_seq"],
                "verification_status": (item.get("verification") or {}).get("ok"),
                "verified_at": item.get("verified_at"),
            }
            for item in checkpoints
        ],
        "last_known_good_checkpoint_id": last_good["id"] if last_good else None,
        "last_successful_recovery": last_recovery,
        "journal_head_seq": last_committed_seq(),
    }


def _age_seconds(created_at: str) -> float:
    try:
        start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - start).total_seconds())
    except ValueError:
        return 0.0


def _last_successful_rollback() -> dict[str, Any] | None:
    conn = connect()
    row = conn.execute(
        """
        SELECT id, updated_at, target_checkpoint_id, terminal_status, phase
        FROM rollback_runs
        WHERE terminal_status = ?
        ORDER BY updated_at DESC LIMIT 1
        """,
        ("COMPLETE",),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "rollback_id": row["id"],
        "completed_at": row["updated_at"],
        "target_checkpoint_id": row["target_checkpoint_id"],
        "status": row["terminal_status"],
    }
