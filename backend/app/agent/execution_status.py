from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..db.models import Task, TaskEvent


class ExecutionPhase(str, Enum):
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    GATHERING = "GATHERING"
    EXECUTING = "EXECUTING"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEGRADED = "DEGRADED"


TERMINAL_PHASES = {
    ExecutionPhase.COMPLETED,
    ExecutionPhase.FAILED,
    ExecutionPhase.CANCELLED,
    ExecutionPhase.DEGRADED,
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def phase_for_event(event: TaskEvent | dict[str, Any]) -> ExecutionPhase:
    get = event.get if isinstance(event, dict) else lambda key, default="": getattr(event, key, default)
    kind = str(get("kind", "") or "").lower()
    stage = str(get("stage", "") or "").lower()
    title = str(get("title", "") or "").lower()
    if kind == "confirm":
        return ExecutionPhase.WAITING_APPROVAL
    if kind == "retry" or stage == "diagnose":
        return ExecutionPhase.RECOVERING
    if kind == "failed" or stage == "failed":
        return ExecutionPhase.FAILED
    if kind == "cancelled" or stage == "cancelled":
        return ExecutionPhase.CANCELLED
    if kind == "completed" or stage == "completed":
        return ExecutionPhase.COMPLETED
    if stage == "verify" or "verif" in title:
        return ExecutionPhase.VERIFYING
    if kind in {"tool", "observation"} or stage in {"act", "observe"}:
        return ExecutionPhase.EXECUTING
    if stage in {"model", "understand"}:
        return ExecutionPhase.GATHERING
    if stage == "plan" or "plan" in title:
        return ExecutionPhase.PLANNING
    return ExecutionPhase.EXECUTING


def project_phase(task: Task, last_event: TaskEvent | None = None) -> ExecutionPhase:
    status = str(task.status or "queued").lower()
    stage = str(task.stage or "queued").lower()
    if task.waiting_for_confirmation:
        return ExecutionPhase.WAITING_APPROVAL
    if status == "queued":
        return ExecutionPhase.QUEUED
    if status == "completed":
        return ExecutionPhase.COMPLETED
    if status == "failed":
        return ExecutionPhase.FAILED
    if status == "cancelled":
        return ExecutionPhase.CANCELLED
    if status == "waiting":
        return ExecutionPhase.WAITING_EXTERNAL
    if stage == "verify":
        return ExecutionPhase.VERIFYING
    if stage == "diagnose":
        return ExecutionPhase.RECOVERING
    if stage == "plan":
        return ExecutionPhase.PLANNING
    if stage in {"understand", "model"}:
        return ExecutionPhase.GATHERING
    if last_event is not None:
        return phase_for_event(last_event)
    return ExecutionPhase.EXECUTING


def normalized_state(task: Task) -> str:
    if task.waiting_for_confirmation or task.status == "waiting":
        return "waiting"
    if task.status in {"queued", "running", "failed", "completed"}:
        return task.status
    return "completed" if task.status == "cancelled" else str(task.status or "queued")


def elapsed_seconds(task: Task, now: datetime | None = None) -> float:
    if task.started_at is None:
        return float(task.duration_seconds or 0)
    if task.finished_at is not None:
        end = _utc(task.finished_at)
    elif task.status in {"queued", "running", "waiting"}:
        end = _utc(now or datetime.now(timezone.utc))
    else:
        return float(task.duration_seconds or 0)
    start = _utc(task.started_at)
    return max(0.0, (end - start).total_seconds()) if start and end else 0.0


def active_worker(task: Task) -> str:
    raw = task.compact_memory or ""
    if raw:
        try:
            state = json.loads(raw)
            worker = state.get("coding_worker") if isinstance(state, dict) else None
            if worker:
                return str(worker)
        except (TypeError, json.JSONDecodeError):
            pass
    return f"Jarvis agent · {task.profile or 'balanced'}"


def verification_summary(task: Task) -> dict[str, Any]:
    verification = str(task.verification or "").strip()
    if task.status == "completed" and verification:
        result = "VERIFIED"
    elif task.status == "failed" and str(task.stage or "").lower() == "verify":
        result = "VERIFICATION_FAILED"
    elif verification:
        result = "PARTIALLY_VERIFIED"
    else:
        result = "NOT_VERIFIED"
    return {
        "result": result,
        "verifier": "Jarvis independent verifier" if verification else "",
        "checks": [verification] if verification else [],
        "evidence_refs": [],
        "warnings": [task.error] if task.error and result != "VERIFIED" else [],
        "timestamp": task.finished_at.isoformat() if task.finished_at else None,
    }
