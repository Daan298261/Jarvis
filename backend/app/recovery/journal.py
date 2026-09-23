from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .admission import assert_write_allowed
from .redaction import redact_mapping
from .store import connect
from .types import CommitState, JOURNAL_SCHEMA_VERSION, JournalOperation

GENESIS_CHAIN = "GENESIS"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _entry_integrity_fields(
    *,
    created_at: str,
    actor: str,
    source: str,
    resource_class: str,
    resource_id: str,
    operation: str,
    schema_version: int,
    correlation_id: str | None,
    payload: dict[str, Any],
    replay_safe: bool,
    risk_tag: str | None,
) -> str:
    body = {
        "created_at": created_at,
        "actor": actor,
        "source": source,
        "resource_class": resource_class,
        "resource_id": resource_id,
        "operation": operation,
        "schema_version": schema_version,
        "correlation_id": correlation_id,
        "payload": payload,
        "replay_safe": replay_safe,
        "risk_tag": risk_tag,
    }
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _chain_hash(prev: str, integrity: str) -> str:
    return hashlib.sha256(f"{prev}:{integrity}".encode("utf-8")).hexdigest()


def _last_chain_hash(conn) -> str:
    row = conn.execute(
        "SELECT chain_hash FROM journal_entries WHERE commit_state = ? ORDER BY seq DESC LIMIT 1",
        (CommitState.COMMITTED.value,),
    ).fetchone()
    return row["chain_hash"] if row else GENESIS_CHAIN


def last_committed_seq(conn=None) -> int:
    own = conn is None
    if own:
        conn = connect()
    row = conn.execute(
        "SELECT seq FROM journal_entries WHERE commit_state = ? ORDER BY seq DESC LIMIT 1",
        (CommitState.COMMITTED.value,),
    ).fetchone()
    if own:
        conn.close()
    return int(row["seq"]) if row else 0


def reconcile_pending_entries() -> list[int]:
    """Fail closed on crash between state mutation and journal commit."""
    conn = connect()
    rows = conn.execute(
        "SELECT seq, resource_class, resource_id, operation, payload_json FROM journal_entries WHERE commit_state = ?",
        (CommitState.PENDING.value,),
    ).fetchall()
    resolved: list[int] = []
    for row in rows:
        seq = int(row["seq"])
        conn.execute(
            "UPDATE journal_entries SET commit_state = ? WHERE seq = ?",
            (CommitState.ABORTED.value, seq),
        )
        resolved.append(seq)
    conn.close()
    return resolved


def verify_journal_chain(limit: int | None = None) -> tuple[bool, str]:
    conn = connect()
    query = (
        "SELECT seq, integrity_hash, chain_hash, commit_state, payload_json "
        "FROM journal_entries WHERE commit_state = ? ORDER BY seq ASC"
    )
    params: tuple = (CommitState.COMMITTED.value,)
    if limit:
        query += " LIMIT ?"
        params = (CommitState.COMMITTED.value, limit)
    rows = conn.execute(query, params).fetchall()
    prev = GENESIS_CHAIN
    for row in rows:
        if row["chain_hash"] != _chain_hash(prev, row["integrity_hash"]):
            conn.close()
            return False, f"chain break at seq {row['seq']}"
        prev = row["chain_hash"]
    conn.close()
    return True, "ok"


def list_journal_entries(
    *,
    after_seq: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        """
        SELECT seq, created_at, actor, source, resource_class, resource_id, operation,
               schema_version, correlation_id, payload_json, integrity_hash, chain_hash,
               replay_safe, commit_state, risk_tag
        FROM journal_entries
        WHERE seq > ? AND commit_state = ?
        ORDER BY seq ASC
        LIMIT ?
        """,
        (after_seq, CommitState.COMMITTED.value, limit),
    ).fetchall()
    conn.close()
    items: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        items.append(
            {
                "seq": row["seq"],
                "created_at": row["created_at"],
                "actor": row["actor"],
                "source": row["source"],
                "resource_class": row["resource_class"],
                "resource_id": row["resource_id"],
                "operation": row["operation"],
                "schema_version": row["schema_version"],
                "correlation_id": row["correlation_id"],
                "payload": payload,
                "integrity_hash": row["integrity_hash"],
                "chain_hash": row["chain_hash"],
                "replay_safe": bool(row["replay_safe"]),
                "risk_tag": row["risk_tag"],
            }
        )
    return items


def journal_mutate(
    *,
    resource_class: str,
    resource_id: str,
    operation: JournalOperation | str,
    actor: str,
    source: str = "api",
    correlation_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    after_fn: Callable[[], dict[str, Any] | None] | None = None,
    replay_safe: bool = False,
    risk_tag: str | None = None,
    apply_fn: Callable[[], None],
    external_effects: list[str] | None = None,
) -> int:
    assert_write_allowed(resource_class, resource_id)
    operation_s = str(operation)
    created_at = _utc_now()
    conn = connect()
    conn.execute("BEGIN IMMEDIATE")
    prev_chain = _last_chain_hash(conn)
    placeholder_payload = {
        "before": redact_mapping(before) if before is not None else None,
        "after": None,
        "external_effects": list(external_effects or []),
    }
    placeholder_integrity = _entry_integrity_fields(
        created_at=created_at,
        actor=actor,
        source=source,
        resource_class=resource_class,
        resource_id=resource_id,
        operation=operation_s,
        schema_version=JOURNAL_SCHEMA_VERSION,
        correlation_id=correlation_id,
        payload=placeholder_payload,
        replay_safe=replay_safe,
        risk_tag=risk_tag,
    )
    chain = _chain_hash(prev_chain, placeholder_integrity)
    cur = conn.execute(
        """
        INSERT INTO journal_entries (
            created_at, actor, source, resource_class, resource_id, operation,
            schema_version, correlation_id, payload_json, integrity_hash, chain_hash,
            replay_safe, commit_state, risk_tag
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            actor,
            source,
            resource_class,
            resource_id,
            operation_s,
            JOURNAL_SCHEMA_VERSION,
            correlation_id,
            json.dumps(placeholder_payload, sort_keys=True),
            placeholder_integrity,
            chain,
            1 if replay_safe else 0,
            CommitState.PENDING.value,
            risk_tag,
        ),
    )
    seq = int(cur.lastrowid)
    try:
        apply_fn()
        final_after = after
        if after_fn is not None:
            final_after = after_fn()
        payload = {
            "before": redact_mapping(before) if before is not None else None,
            "after": redact_mapping(final_after) if final_after is not None else None,
            "external_effects": list(external_effects or []),
        }
        integrity = _entry_integrity_fields(
            created_at=created_at,
            actor=actor,
            source=source,
            resource_class=resource_class,
            resource_id=resource_id,
            operation=operation_s,
            schema_version=JOURNAL_SCHEMA_VERSION,
            correlation_id=correlation_id,
            payload=payload,
            replay_safe=replay_safe,
            risk_tag=risk_tag,
        )
        chain = _chain_hash(prev_chain, integrity)
        conn.execute(
            """
            UPDATE journal_entries
            SET payload_json = ?, integrity_hash = ?, chain_hash = ?, commit_state = ?
            WHERE seq = ?
            """,
            (
                json.dumps(payload, sort_keys=True),
                integrity,
                chain,
                CommitState.COMMITTED.value,
                seq,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute(
            "UPDATE journal_entries SET commit_state = ? WHERE seq = ?",
            (CommitState.ABORTED.value, seq),
        )
        conn.execute("COMMIT")
        raise
    finally:
        conn.close()
    return seq


def simulate_crash_after_apply(
    *,
    resource_class: str,
    resource_id: str,
    operation: JournalOperation | str,
    actor: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    apply_fn: Callable[[], None],
) -> int:
    """Test-only: leave journal row pending after apply_fn (crash simulation)."""
    operation_s = str(operation)
    payload = {
        "before": redact_mapping(before) if before is not None else None,
        "after": redact_mapping(after) if after is not None else None,
        "external_effects": [],
    }
    created_at = _utc_now()
    integrity = _entry_integrity_fields(
        created_at=created_at,
        actor=actor,
        source="test",
        resource_class=resource_class,
        resource_id=resource_id,
        operation=operation_s,
        schema_version=JOURNAL_SCHEMA_VERSION,
        correlation_id=None,
        payload=payload,
        replay_safe=False,
        risk_tag="test_crash",
    )
    conn = connect()
    conn.execute("BEGIN IMMEDIATE")
    prev_chain = _last_chain_hash(conn)
    chain = _chain_hash(prev_chain, integrity)
    cur = conn.execute(
        """
        INSERT INTO journal_entries (
            created_at, actor, source, resource_class, resource_id, operation,
            schema_version, correlation_id, payload_json, integrity_hash, chain_hash,
            replay_safe, commit_state, risk_tag
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            actor,
            "test",
            resource_class,
            resource_id,
            operation_s,
            JOURNAL_SCHEMA_VERSION,
            None,
            json.dumps(payload, sort_keys=True),
            integrity,
            chain,
            0,
            CommitState.PENDING.value,
            "test_crash",
        ),
    )
    seq = int(cur.lastrowid)
    apply_fn()
    conn.execute("COMMIT")
    conn.close()
    return seq


def corrupt_entry_hash(seq: int) -> None:
    conn = connect()
    conn.execute("UPDATE journal_entries SET integrity_hash = ? WHERE seq = ?", ("deadbeef", seq))
    conn.close()


def prune_through_seq(pruned_through: int, *, retained_checkpoint_id: str, actor: str) -> int:
    conn = connect()
    conn.execute("BEGIN IMMEDIATE")
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM journal_entries WHERE seq <= ? AND commit_state = ?",
        (pruned_through, CommitState.COMMITTED.value),
    ).fetchone()["c"]
    conn.execute(
        "DELETE FROM journal_entries WHERE seq <= ? AND commit_state = ?",
        (pruned_through, CommitState.COMMITTED.value),
    )
    conn.execute(
        """
        INSERT INTO prune_audit (created_at, actor, pruned_through_seq, retained_checkpoint_id, detail_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (_utc_now(), actor, pruned_through, retained_checkpoint_id, json.dumps({"deleted": count})),
    )
    conn.execute("COMMIT")
    conn.close()
    return int(count)
