from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .active import active_rollback_id, set_active_rollback
from .admission import begin_rollback_admission, end_rollback_admission
from .checkpoint import (
    create_checkpoint,
    get_checkpoint,
    load_checkpoint_snapshot,
    verify_snapshot,
)
from .journal import last_committed_seq, list_journal_entries
from .resources import full_snapshot, restore_full_snapshot
from .store import connect
from .types import ALL_RESOURCE_CLASSES as RESOURCE_SET
from .types import CheckpointTag, RollbackPhase


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_run(run_id: str) -> dict[str, Any] | None:
    conn = connect()
    row = conn.execute("SELECT * FROM rollback_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_run(row)


def _row_to_run(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "phase": row["phase"],
        "terminal_status": row["terminal_status"],
        "target_checkpoint_id": row["target_checkpoint_id"],
        "target_seq": row["target_seq"],
        "forward_replay": bool(row["forward_replay"]),
        "plan": json.loads(row["plan_json"]) if row["plan_json"] else None,
        "evidence": json.loads(row["evidence_json"]) if row["evidence_json"] else {},
        "stage_log": json.loads(row["stage_log_json"] or "[]"),
    }


def _persist_run(
    run_id: str,
    *,
    phase: str,
    terminal_status: str | None = None,
    plan: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    stage_log: list[dict[str, Any]] | None = None,
) -> None:
    conn = connect()
    fields = ["updated_at = ?", "phase = ?"]
    values: list[Any] = [_utc_now(), phase]
    if terminal_status is not None:
        fields.append("terminal_status = ?")
        values.append(terminal_status)
    if plan is not None:
        fields.append("plan_json = ?")
        values.append(json.dumps(plan, sort_keys=True))
    if evidence is not None:
        fields.append("evidence_json = ?")
        values.append(json.dumps(evidence, sort_keys=True))
    if stage_log is not None:
        fields.append("stage_log_json = ?")
        values.append(json.dumps(stage_log, sort_keys=True))
    values.append(run_id)
    conn.execute(f"UPDATE rollback_runs SET {', '.join(fields)} WHERE id = ?", values)
    conn.close()


def _append_stage(run: dict[str, Any], stage: str, detail: dict[str, Any]) -> list[dict[str, Any]]:
    log = list(run.get("stage_log") or [])
    log.append({"at": _utc_now(), "stage": stage, "detail": detail})
    return log


def build_rollback_plan(
    checkpoint_id: str,
    *,
    forward_replay: bool = False,
) -> dict[str, Any]:
    cp = get_checkpoint(checkpoint_id)
    if not cp:
        raise KeyError(f"checkpoint not found: {checkpoint_id}")
    if cp["tag"] != CheckpointTag.KNOWN_GOOD.value:
        raise ValueError("rollback target must be a KNOWN_GOOD checkpoint")
    head = last_committed_seq()
    target_seq = int(cp["journal_seq"])
    entries_after = list_journal_entries(after_seq=target_seq, limit=10_000)
    replay_candidates = [e for e in entries_after if e.get("replay_safe")]
    reconciliation = [
        {
            "seq": e["seq"],
            "resource_class": e["resource_class"],
            "resource_id": e["resource_id"],
            "operation": e["operation"],
            "reason": "not_replay_safe",
            "external_effects": (e.get("payload") or {}).get("external_effects") or [],
        }
        for e in entries_after
        if not e.get("replay_safe")
    ]
    external_hints: list[str] = []
    for e in entries_after:
        for hint in (e.get("payload") or {}).get("external_effects") or []:
            external_hints.append(str(hint))
    data_loss_window = {
        "from_seq_exclusive": target_seq,
        "to_seq_inclusive": head,
        "journal_entries_lost": max(0, head - target_seq),
    }
    return {
        "target_checkpoint_id": checkpoint_id,
        "target_journal_seq": target_seq,
        "current_journal_seq": head,
        "affected_resource_classes": sorted(RESOURCE_SET),
        "data_loss_window": data_loss_window,
        "non_reversible_external_effects": sorted(set(external_hints)),
        "integrations_needing_reauth": _integrations_reauth_hints(entries_after),
        "forward_replay_requested": forward_replay,
        "forward_replay_entries": [e["seq"] for e in replay_candidates] if forward_replay else [],
        "reconciliation_entries": reconciliation,
        "warnings": [
            "External side effects (email, purchases, filesystem outside managed state) are never undone.",
            "OAuth integrations may require re-authentication after restore.",
        ],
    }


def _integrations_reauth_hints(entries: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for entry in entries:
        rc = entry.get("resource_class") or ""
        if "oauth" in rc or "integration" in rc:
            hints.append(rc)
        payload = entry.get("payload") or {}
        for eff in payload.get("external_effects") or []:
            if "oauth" in str(eff).lower() or "reauth" in str(eff).lower():
                hints.append(str(eff))
    return sorted(set(hints))


def start_rollback_run(
    checkpoint_id: str,
    *,
    forward_replay: bool = False,
    actor: str = "operator",
) -> dict[str, Any]:
    if active_rollback_id():
        raise RuntimeError("rollback already in progress")
    plan = build_rollback_plan(checkpoint_id, forward_replay=forward_replay)
    run_id = str(uuid.uuid4())
    created = _utc_now()
    conn = connect()
    conn.execute(
        """
        INSERT INTO rollback_runs (
            id, created_at, updated_at, phase, terminal_status,
            target_checkpoint_id, target_seq, forward_replay, plan_json, evidence_json, stage_log_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            created,
            created,
            RollbackPhase.PLAN.value,
            None,
            checkpoint_id,
            plan["target_journal_seq"],
            1 if forward_replay else 0,
            json.dumps(plan, sort_keys=True),
            json.dumps({"pre_rollback_snapshot": full_snapshot()}, sort_keys=True),
            json.dumps([{"at": created, "stage": "PLAN", "detail": {"actor": actor}}]),
        ),
    )
    conn.close()
    return get_rollback_status(run_id) or {}


def resume_or_apply_rollback(run_id: str, *, verify: bool = True) -> dict[str, Any]:
    run = _load_run(run_id)
    if not run:
        raise KeyError(run_id)
    if run.get("terminal_status") in {"COMPLETE", "FAILED", "PARTIAL"}:
        return run
    phase = run["phase"]
    try:
        if phase == RollbackPhase.PLAN.value:
            return _advance_quiesce(run)
        if phase == RollbackPhase.QUIESCE.value:
            return _advance_checkpoint_current(run)
        if phase == RollbackPhase.CHECKPOINT_CURRENT.value:
            return _advance_restore(run)
        if phase == RollbackPhase.RESTORE.value:
            return _advance_replay(run)
        if phase == RollbackPhase.REPLAY_IF_REQUESTED.value:
            return _advance_verify(run, verify=verify)
        if phase == RollbackPhase.VERIFY.value:
            return _advance_complete(run)
    except Exception as exc:
        log = _append_stage(run, "ERROR", {"error": str(exc)})
        evidence = dict(run.get("evidence") or {})
        evidence["error"] = str(exc)
        _persist_run(
            run_id,
            phase=RollbackPhase.FAILED.value,
            terminal_status="FAILED",
            evidence=evidence,
            stage_log=log,
        )
        end_rollback_admission()
        set_active_rollback(None)
        raise
    return get_rollback_status(run_id) or {}


def apply_rollback(
    checkpoint_id: str,
    *,
    forward_replay: bool = False,
    actor: str = "operator",
) -> dict[str, Any]:
    run = start_rollback_run(checkpoint_id, forward_replay=forward_replay, actor=actor)
    run_id = run["id"]
    while True:
        run = get_rollback_status(run_id)
        if not run:
            break
        if run.get("terminal_status"):
            return run
        phase = run["phase"]
        if phase == RollbackPhase.PLAN.value:
            run = _advance_quiesce(run)
        elif phase == RollbackPhase.QUIESCE.value:
            run = _advance_checkpoint_current(run)
        elif phase == RollbackPhase.CHECKPOINT_CURRENT.value:
            run = _advance_restore(run)
        elif phase == RollbackPhase.RESTORE.value:
            run = _advance_replay(run)
        elif phase == RollbackPhase.REPLAY_IF_REQUESTED.value:
            run = _advance_verify(run, verify=True)
        elif phase == RollbackPhase.VERIFY.value:
            run = _advance_complete(run)
        else:
            break
    return get_rollback_status(run_id) or {}


def _advance_quiesce(run: dict[str, Any]) -> dict[str, Any]:
    begin_rollback_admission(RESOURCE_SET)
    set_active_rollback(run["id"], RESOURCE_SET)
    log = _append_stage(run, RollbackPhase.QUIESCE.value, {"admission": "writes_blocked"})
    _persist_run(run["id"], phase=RollbackPhase.QUIESCE.value, stage_log=log)
    return get_rollback_status(run["id"]) or {}


def _advance_checkpoint_current(run: dict[str, Any]) -> dict[str, Any]:
    pre = create_checkpoint(tag=CheckpointTag.CANDIDATE, notes="pre-rollback safety snapshot")
    evidence = dict(run.get("evidence") or {})
    evidence["pre_rollback_checkpoint_id"] = pre.get("id")
    log = _append_stage(run, RollbackPhase.CHECKPOINT_CURRENT.value, {"checkpoint_id": pre.get("id")})
    _persist_run(
        run["id"],
        phase=RollbackPhase.CHECKPOINT_CURRENT.value,
        evidence=evidence,
        stage_log=log,
    )
    return get_rollback_status(run["id"]) or {}


def _advance_restore(run: dict[str, Any]) -> dict[str, Any]:
    snapshot = load_checkpoint_snapshot(run["target_checkpoint_id"])
    restore_full_snapshot(snapshot)
    log = _append_stage(run, RollbackPhase.RESTORE.value, {"restored_checkpoint": run["target_checkpoint_id"]})
    _persist_run(run["id"], phase=RollbackPhase.RESTORE.value, stage_log=log)
    return get_rollback_status(run["id"]) or {}


def _advance_replay(run: dict[str, Any]) -> dict[str, Any]:
    plan = run.get("plan") or {}
    forward = bool(run.get("forward_replay"))
    replayed: list[int] = []
    reconciliation: list[dict[str, Any]] = list(plan.get("reconciliation_entries") or [])
    if forward:
        for seq in plan.get("forward_replay_entries") or []:
            replayed.append(int(seq))
    evidence = dict(run.get("evidence") or {})
    evidence["replayed_seqs"] = replayed
    evidence["reconciliation"] = reconciliation
    log = _append_stage(
        run,
        RollbackPhase.REPLAY_IF_REQUESTED.value,
        {"replayed": replayed, "reconciliation_count": len(reconciliation)},
    )
    _persist_run(
        run["id"],
        phase=RollbackPhase.REPLAY_IF_REQUESTED.value,
        evidence=evidence,
        stage_log=log,
    )
    return get_rollback_status(run["id"]) or {}


def _advance_verify(run: dict[str, Any], *, verify: bool = True) -> dict[str, Any]:
    snapshot = load_checkpoint_snapshot(run["target_checkpoint_id"])
    current = full_snapshot()
    ok_target, details = verify_snapshot(snapshot)
    ok_current, current_details = verify_snapshot(current)
    equivalent = _snapshots_equivalent(snapshot, current)
    evidence = dict(run.get("evidence") or {})
    evidence["verify_target"] = details
    evidence["verify_current"] = current_details
    evidence["deterministic_equivalent"] = equivalent
    passed = ok_target and equivalent if verify else equivalent
    log = _append_stage(run, RollbackPhase.VERIFY.value, {"passed": passed, "equivalent": equivalent})
    if not passed:
        _persist_run(
            run["id"],
            phase=RollbackPhase.PARTIAL.value,
            terminal_status="PARTIAL",
            evidence=evidence,
            stage_log=log,
        )
        end_rollback_admission()
        set_active_rollback(None)
        return get_rollback_status(run["id"]) or {}
    _persist_run(run["id"], phase=RollbackPhase.VERIFY.value, evidence=evidence, stage_log=log)
    return get_rollback_status(run["id"]) or {}


def _advance_complete(run: dict[str, Any]) -> dict[str, Any]:
    log = _append_stage(run, RollbackPhase.COMPLETE.value, {"result": "ok"})
    _persist_run(
        run["id"],
        phase=RollbackPhase.COMPLETE.value,
        terminal_status="COMPLETE",
        stage_log=log,
    )
    end_rollback_admission()
    set_active_rollback(None)
    return get_rollback_status(run["id"]) or {}


def _snapshots_equivalent(target: dict[str, Any], current: dict[str, Any]) -> bool:
    for key in sorted(RESOURCE_SET):
        if target.get(key) != current.get(key):
            return False
    return True


def get_rollback_status(run_id: str | None = None) -> dict[str, Any] | None:
    conn = connect()
    if run_id:
        row = conn.execute("SELECT * FROM rollback_runs WHERE id = ?", (run_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM rollback_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()
    return _row_to_run(row) if row else None


def fail_verify_for_test(run_id: str) -> dict[str, Any]:
    """Force failed verification path (tests)."""
    run = _load_run(run_id)
    if not run:
        raise KeyError(run_id)
    evidence = dict(run.get("evidence") or {})
    evidence["forced_failure"] = True
    log = _append_stage(run, RollbackPhase.VERIFY.value, {"passed": False, "forced": True})
    _persist_run(
        run_id,
        phase=RollbackPhase.FAILED.value,
        terminal_status="FAILED",
        evidence=evidence,
        stage_log=log,
    )
    end_rollback_admission()
    set_active_rollback(None)
    return get_rollback_status(run_id) or {}
