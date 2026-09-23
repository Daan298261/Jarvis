from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .audit import record_breaker_audit, reset_breaker_audit
from .ids import automation_actor_id
from .outcomes import TerminalOutcome

_lock = threading.RLock()

BREAKER_ACTIVE = "ACTIVE"
BREAKER_DEGRADED = "DEGRADED"
BREAKER_DISABLED_BY_FAILURE = "DISABLED_BY_FAILURE"

DEFAULT_FAILURE_THRESHOLD = 3
STATE_FILE = "automations.json"
RUNS_FILE = "runs.json"


class AutomationBreakerError(ValueError):
    """Invalid breaker operation."""


@dataclass
class AutomationBreakerRecord:
    automation_id: str
    consecutive_failure_count: int = 0
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    last_failure_at: str | None = None
    last_failure_summary: str = ""
    breaker_state: str = BREAKER_ACTIVE
    disabled_at: str | None = None
    recent_failed_run_ids: list[str] = field(default_factory=list)
    kind: str = "generic"
    ref_id: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdmissionResult:
    allowed: bool
    automation_id: str
    breaker_state: str
    reason: str = ""
    suppressed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _root() -> Path:
    path = data_dir() / "automation-breaker"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return _root() / STATE_FILE


def _runs_path() -> Path:
    return _root() / RUNS_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_breaker_state(count: int, threshold: int, disabled_at: str | None) -> str:
    if disabled_at or count >= threshold:
        return BREAKER_DISABLED_BY_FAILURE
    if count > 0:
        return BREAKER_DEGRADED
    return BREAKER_ACTIVE


def _record_from_row(row: dict[str, Any]) -> AutomationBreakerRecord:
    threshold = int(row.get("failure_threshold") or DEFAULT_FAILURE_THRESHOLD)
    count = int(row.get("consecutive_failure_count") or 0)
    disabled_at = row.get("disabled_at")
    state = str(row.get("breaker_state") or _derive_breaker_state(count, threshold, disabled_at))
    return AutomationBreakerRecord(
        automation_id=str(row.get("automation_id") or ""),
        consecutive_failure_count=count,
        failure_threshold=threshold,
        last_failure_at=row.get("last_failure_at"),
        last_failure_summary=str(row.get("last_failure_summary") or ""),
        breaker_state=state,
        disabled_at=disabled_at,
        recent_failed_run_ids=list(row.get("recent_failed_run_ids") or []),
        kind=str(row.get("kind") or "generic"),
        ref_id=str(row.get("ref_id") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _load_state_unlocked() -> dict[str, AutomationBreakerRecord]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, AutomationBreakerRecord] = {}
    for key, row in raw.items():
        if not isinstance(row, dict):
            continue
        record = _record_from_row({**row, "automation_id": row.get("automation_id") or key})
        out[str(key)] = record
    return out


def _save_state_unlocked(state: dict[str, AutomationBreakerRecord]) -> None:
    payload = {key: item.as_dict() for key, item in state.items()}
    _state_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_runs_unlocked() -> dict[str, dict[str, Any]]:
    path = _runs_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_runs_unlocked(runs: dict[str, dict[str, Any]]) -> None:
    _runs_path().write_text(json.dumps(runs, indent=2), encoding="utf-8")


def reset_automation_breaker_store() -> None:
    with _lock:
        for path in (_state_path(), _runs_path()):
            if path.exists():
                path.unlink()
    reset_breaker_audit()


def ensure_automation(
    automation_id: str,
    *,
    failure_threshold: int | None = None,
    kind: str = "generic",
    ref_id: str = "",
) -> AutomationBreakerRecord:
    if not automation_id.strip():
        raise AutomationBreakerError("automation_id is required")
    threshold = int(failure_threshold or DEFAULT_FAILURE_THRESHOLD)
    if threshold < 1:
        raise AutomationBreakerError("failure_threshold must be at least 1")
    with _lock:
        state = _load_state_unlocked()
        existing = state.get(automation_id)
        if existing is not None:
            if failure_threshold is not None:
                existing.failure_threshold = threshold
            if kind:
                existing.kind = kind
            if ref_id:
                existing.ref_id = ref_id
            existing.breaker_state = _derive_breaker_state(
                existing.consecutive_failure_count,
                existing.failure_threshold,
                existing.disabled_at,
            )
            existing.updated_at = _utc_now()
            state[automation_id] = existing
            _save_state_unlocked(state)
            return existing
        now = _utc_now()
        record = AutomationBreakerRecord(
            automation_id=automation_id,
            failure_threshold=threshold,
            kind=kind,
            ref_id=ref_id,
            updated_at=now,
        )
        state[automation_id] = record
        _save_state_unlocked(state)
        return record


def get_automation_breaker(automation_id: str) -> AutomationBreakerRecord | None:
    with _lock:
        return _load_state_unlocked().get(automation_id)


def list_automation_breakers() -> list[AutomationBreakerRecord]:
    with _lock:
        return list(_load_state_unlocked().values())


def set_failure_threshold(automation_id: str, threshold: int, *, actor: str = "owner") -> AutomationBreakerRecord:
    record = ensure_automation(automation_id, failure_threshold=threshold)
    record_breaker_audit(
        event_type="threshold_updated",
        automation_id=automation_id,
        actor=actor,
        detail={"failure_threshold": threshold},
    )
    return record


def admit_automatic_trigger(
    automation_id: str,
    *,
    run_id: str,
    trigger: str = "schedule",
) -> AdmissionResult:
    """Gate scheduled/event automatic wakeups. Fails closed when disabled."""
    ensure_automation(automation_id)
    with _lock:
        state = _load_state_unlocked()
        record = state.get(automation_id)
        if record is None:
            return AdmissionResult(False, automation_id, BREAKER_ACTIVE, reason="automation not registered")
        if record.breaker_state == BREAKER_DISABLED_BY_FAILURE or record.disabled_at:
            record_breaker_audit(
                event_type="trigger_suppressed",
                automation_id=automation_id,
                detail={"trigger": trigger, "run_id": run_id, "breaker_state": record.breaker_state},
            )
            return AdmissionResult(
                allowed=False,
                automation_id=automation_id,
                breaker_state=record.breaker_state,
                reason="automation disabled by failure circuit breaker",
                suppressed=True,
            )
        runs = _load_runs_unlocked()
        if run_id in runs and runs[run_id].get("finalized"):
            record_breaker_audit(
                event_type="trigger_suppressed",
                automation_id=automation_id,
                detail={"trigger": trigger, "run_id": run_id, "reason": "duplicate_terminal_run"},
            )
            return AdmissionResult(
                allowed=False,
                automation_id=automation_id,
                breaker_state=record.breaker_state,
                reason="duplicate idempotent run suppressed",
                suppressed=True,
            )
        runs[run_id] = {
            "automation_id": automation_id,
            "run_id": run_id,
            "trigger": trigger,
            "admitted_at": _utc_now(),
            "finalized": False,
            "task_id": runs.get(run_id, {}).get("task_id"),
        }
        _save_runs_unlocked(runs)
        return AdmissionResult(
            allowed=True,
            automation_id=automation_id,
            breaker_state=record.breaker_state,
        )


def bind_run_to_task(run_id: str, task_id: str) -> None:
    with _lock:
        runs = _load_runs_unlocked()
        row = runs.get(run_id)
        if row is None:
            runs[run_id] = {
                "run_id": run_id,
                "task_id": task_id,
                "admitted_at": _utc_now(),
                "finalized": False,
            }
        else:
            row["task_id"] = task_id
            runs[run_id] = row
        _save_runs_unlocked(runs)
        by_task = {v.get("task_id"): k for k, v in runs.items() if v.get("task_id")}
        runs["_task_index"] = by_task
        _save_runs_unlocked(runs)


def _find_run_for_task(task_id: str) -> tuple[str, dict[str, Any]] | None:
    runs = _load_runs_unlocked()
    index = runs.get("_task_index")
    if isinstance(index, dict) and task_id in index:
        run_id = str(index[task_id])
        row = runs.get(run_id)
        if isinstance(row, dict):
            return run_id, row
    for run_id, row in runs.items():
        if run_id.startswith("_") or not isinstance(row, dict):
            continue
        if row.get("task_id") == task_id:
            return run_id, row
    return None


def finalize_run_outcome(
    automation_id: str,
    run_id: str,
    outcome: TerminalOutcome,
    *,
    summary: str = "",
    task_id: str | None = None,
) -> AutomationBreakerRecord:
    """Apply one terminal normalized outcome per run (retries collapse here)."""
    with _lock:
        state = _load_state_unlocked()
        record = state.get(automation_id)
        if record is None:
            record = ensure_automation(automation_id)
            state = _load_state_unlocked()
            record = state[automation_id]

        runs = _load_runs_unlocked()
        row = runs.get(run_id)
        if row and row.get("finalized"):
            return record
        if row is None:
            row = {
                "automation_id": automation_id,
                "run_id": run_id,
                "admitted_at": _utc_now(),
                "finalized": False,
            }
            runs[run_id] = row
        if task_id:
            row["task_id"] = task_id

        if outcome.increments_failure_counter():
            record.consecutive_failure_count += 1
            record.last_failure_at = _utc_now()
            record.last_failure_summary = (summary or "terminal failure")[:500]
            failed = list(record.recent_failed_run_ids)
            link = task_id or run_id
            if link and link not in failed:
                failed.append(link)
            record.recent_failed_run_ids = failed[-10:]
            if record.consecutive_failure_count >= record.failure_threshold:
                record.disabled_at = record.disabled_at or _utc_now()
                record.breaker_state = BREAKER_DISABLED_BY_FAILURE
                record_breaker_audit(
                    event_type="breaker_tripped",
                    automation_id=automation_id,
                    detail={
                        "consecutive_failure_count": record.consecutive_failure_count,
                        "failure_threshold": record.failure_threshold,
                        "last_failure_summary": record.last_failure_summary,
                        "run_id": run_id,
                    },
                )
            else:
                record.breaker_state = BREAKER_DEGRADED
        elif outcome.resets_failure_counter():
            record.consecutive_failure_count = 0
            record.breaker_state = BREAKER_ACTIVE
            record.last_failure_summary = ""
            record_breaker_audit(
                event_type="failure_counter_reset",
                automation_id=automation_id,
                detail={"run_id": run_id, "task_id": task_id},
            )
        else:
            record.breaker_state = _derive_breaker_state(
                record.consecutive_failure_count,
                record.failure_threshold,
                record.disabled_at,
            )

        record.updated_at = _utc_now()
        state[automation_id] = record
        row["finalized"] = True
        row["outcome"] = outcome.value
        row["finalized_at"] = _utc_now()
        runs[run_id] = row
        if task_id:
            index = runs.get("_task_index")
            if not isinstance(index, dict):
                index = {}
            index[task_id] = run_id
            runs["_task_index"] = index
        _save_runs_unlocked(runs)
        _save_state_unlocked(state)
        return record


def reenable_automation(automation_id: str, *, actor: str) -> AutomationBreakerRecord:
    actor_norm = (actor or "").strip()
    if not actor_norm:
        raise AutomationBreakerError("actor is required for re-enable")
    if actor_norm == automation_actor_id(automation_id):
        raise AutomationBreakerError("automation cannot re-enable itself")
    if actor_norm.startswith("automation:") and automation_id in actor_norm:
        raise AutomationBreakerError("automation cannot re-enable itself")

    with _lock:
        state = _load_state_unlocked()
        record = state.get(automation_id)
        if record is None:
            record = ensure_automation(automation_id)
            state = _load_state_unlocked()
            record = state[automation_id]

        already_active = (
            record.breaker_state == BREAKER_ACTIVE
            and record.consecutive_failure_count == 0
            and not record.disabled_at
        )
        record.consecutive_failure_count = 0
        record.breaker_state = BREAKER_ACTIVE
        record.disabled_at = None
        record.last_failure_at = None
        record.last_failure_summary = ""
        record.updated_at = _utc_now()
        state[automation_id] = record
        _save_state_unlocked(state)

    record_breaker_audit(
        event_type="reenable" if not already_active else "reenable_idempotent",
        automation_id=automation_id,
        actor=actor_norm,
        detail={"acknowledged": True},
    )
    return record


def normalize_task_terminal(
    *,
    status: str,
    verification: str = "",
    error: str = "",
    waiting_for_confirmation: bool = False,
    duplicate_suppressed: bool = False,
    skipped: bool = False,
) -> TerminalOutcome:
    status_norm = (status or "").strip().lower()
    if duplicate_suppressed:
        return TerminalOutcome.DUPLICATE_SUPPRESSED
    if skipped:
        return TerminalOutcome.SKIPPED
    if waiting_for_confirmation:
        return TerminalOutcome.APPROVAL_WAIT
    if status_norm == "cancelled":
        return TerminalOutcome.CANCELLED
    if status_norm == "failed":
        return TerminalOutcome.FAILURE
    if status_norm == "completed":
        if (verification or "").strip():
            return TerminalOutcome.SUCCESS
        return TerminalOutcome.NO_OP
    return TerminalOutcome.NO_OP


def on_task_terminal(
    task_id: str,
    *,
    status: str,
    verification: str = "",
    error: str = "",
    waiting_for_confirmation: bool = False,
) -> None:
    status_norm = (status or "").strip().lower()
    if status_norm not in {"completed", "failed", "cancelled"}:
        return
    outcome = normalize_task_terminal(
        status=status,
        verification=verification,
        error=error,
        waiting_for_confirmation=waiting_for_confirmation,
    )
    if outcome is TerminalOutcome.APPROVAL_WAIT:
        return

    with _lock:
        found = _find_run_for_task(task_id)
    if not found:
        return
    run_id, row = found
    automation_id = str(row.get("automation_id") or "")
    if not automation_id:
        return
    finalize_run_outcome(
        automation_id,
        run_id,
        outcome,
        summary=(error or verification or outcome.value)[:500],
        task_id=task_id,
    )
