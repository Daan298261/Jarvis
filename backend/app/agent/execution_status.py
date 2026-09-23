from __future__ import annotations

import json
import os
import re
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

ExternalWaitKind = str  # rate_limit | remote_job | dependency_unavailable | other

# Observable projection only — not a workflow scheduler. Illegal worker hints are ignored.
LEGAL_PHASE_TRANSITIONS: dict[ExecutionPhase, set[ExecutionPhase]] = {
    ExecutionPhase.QUEUED: {
        ExecutionPhase.PLANNING,
        ExecutionPhase.GATHERING,
        ExecutionPhase.EXECUTING,
        ExecutionPhase.WAITING_EXTERNAL,
        ExecutionPhase.WAITING_APPROVAL,
        ExecutionPhase.CANCELLED,
        ExecutionPhase.FAILED,
    },
    ExecutionPhase.PLANNING: {
        ExecutionPhase.GATHERING,
        ExecutionPhase.EXECUTING,
        ExecutionPhase.WAITING_EXTERNAL,
        ExecutionPhase.WAITING_APPROVAL,
        ExecutionPhase.RECOVERING,
        ExecutionPhase.CANCELLED,
        ExecutionPhase.FAILED,
        ExecutionPhase.QUEUED,
    },
    ExecutionPhase.GATHERING: {
        ExecutionPhase.PLANNING,
        ExecutionPhase.EXECUTING,
        ExecutionPhase.WAITING_EXTERNAL,
        ExecutionPhase.WAITING_APPROVAL,
        ExecutionPhase.RECOVERING,
        ExecutionPhase.CANCELLED,
        ExecutionPhase.FAILED,
    },
    ExecutionPhase.EXECUTING: {
        ExecutionPhase.PLANNING,
        ExecutionPhase.GATHERING,
        ExecutionPhase.WAITING_EXTERNAL,
        ExecutionPhase.WAITING_APPROVAL,
        ExecutionPhase.VERIFYING,
        ExecutionPhase.RECOVERING,
        ExecutionPhase.FINALIZING,
        ExecutionPhase.COMPLETED,
        ExecutionPhase.DEGRADED,
        ExecutionPhase.FAILED,
        ExecutionPhase.CANCELLED,
    },
    ExecutionPhase.WAITING_EXTERNAL: {
        ExecutionPhase.EXECUTING,
        ExecutionPhase.GATHERING,
        ExecutionPhase.RECOVERING,
        ExecutionPhase.CANCELLED,
        ExecutionPhase.FAILED,
    },
    ExecutionPhase.WAITING_APPROVAL: {
        ExecutionPhase.EXECUTING,
        ExecutionPhase.PLANNING,
        ExecutionPhase.CANCELLED,
        ExecutionPhase.FAILED,
    },
    ExecutionPhase.VERIFYING: {
        ExecutionPhase.EXECUTING,
        ExecutionPhase.RECOVERING,
        ExecutionPhase.FINALIZING,
        ExecutionPhase.COMPLETED,
        ExecutionPhase.DEGRADED,
        ExecutionPhase.FAILED,
        ExecutionPhase.CANCELLED,
    },
    ExecutionPhase.RECOVERING: {
        ExecutionPhase.PLANNING,
        ExecutionPhase.GATHERING,
        ExecutionPhase.EXECUTING,
        ExecutionPhase.VERIFYING,
        ExecutionPhase.FAILED,
        ExecutionPhase.CANCELLED,
    },
    ExecutionPhase.FINALIZING: {
        ExecutionPhase.COMPLETED,
        ExecutionPhase.DEGRADED,
        ExecutionPhase.FAILED,
        ExecutionPhase.CANCELLED,
    },
    ExecutionPhase.COMPLETED: set(),
    ExecutionPhase.FAILED: set(),
    ExecutionPhase.CANCELLED: set(),
    ExecutionPhase.DEGRADED: set(),
}

_DEFAULT_STALE_SECONDS: dict[ExecutionPhase, float] = {
    ExecutionPhase.WAITING_EXTERNAL: 300.0,
    ExecutionPhase.WAITING_APPROVAL: 86_400.0,
    ExecutionPhase.VERIFYING: 600.0,
    ExecutionPhase.RECOVERING: 900.0,
    ExecutionPhase.PLANNING: 600.0,
    ExecutionPhase.GATHERING: 600.0,
    ExecutionPhase.EXECUTING: 1_200.0,
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _utc(value)
    return normalized.isoformat() if normalized else None


def is_legal_phase_transition(
    previous: ExecutionPhase,
    next_phase: ExecutionPhase,
) -> bool:
    if previous == next_phase:
        return True
    if previous in TERMINAL_PHASES:
        return False
    allowed = LEGAL_PHASE_TRANSITIONS.get(previous, set())
    return next_phase in allowed


def reconcile_projected_phase(
    previous: ExecutionPhase,
    hinted: ExecutionPhase,
) -> ExecutionPhase:
    """Drop conflicting worker hints; keep orchestrator-stronger terminal state."""
    if hinted == previous:
        return previous
    if is_legal_phase_transition(previous, hinted):
        return hinted
    if hinted in TERMINAL_PHASES and previous not in TERMINAL_PHASES:
        return hinted
    return previous


def phase_for_event(event: TaskEvent | dict[str, Any]) -> ExecutionPhase:
    get = event.get if isinstance(event, dict) else lambda key, default="": getattr(event, key, default)
    kind = str(get("kind", "") or "").lower()
    stage = str(get("stage", "") or "").lower()
    title = str(get("title", "") or "").lower()
    detail = str(get("detail", "") or "")
    if kind == "confirm":
        return ExecutionPhase.WAITING_APPROVAL
    if kind in {"external_wait", "waiting_external"}:
        return ExecutionPhase.WAITING_EXTERNAL
    if kind == "retry" or stage == "diagnose":
        return ExecutionPhase.RECOVERING
    if kind == "failed" or stage == "failed":
        return ExecutionPhase.FAILED
    if kind == "cancelled" or stage == "cancelled":
        return ExecutionPhase.CANCELLED
    if kind == "completed" or stage == "completed":
        return ExecutionPhase.COMPLETED
    if stage == "finalize" or "finaliz" in title:
        return ExecutionPhase.FINALIZING
    if stage == "verify" or "verif" in title or kind == "verification_request":
        return ExecutionPhase.VERIFYING
    if kind in {"tool", "observation"} or stage in {"act", "observe"}:
        return ExecutionPhase.EXECUTING
    if stage in {"model", "understand"}:
        return ExecutionPhase.GATHERING
    if stage == "plan" or "plan" in title:
        return ExecutionPhase.PLANNING
    blocked = _external_kind_from_detail(detail)
    if blocked:
        return ExecutionPhase.WAITING_EXTERNAL
    return ExecutionPhase.EXECUTING


def _compact_state(task: Task) -> dict[str, Any]:
    raw = task.compact_memory or ""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _observability_blob(task: Task) -> dict[str, Any]:
    state = _compact_state(task)
    obs = state.get("observability")
    return obs if isinstance(obs, dict) else {}


def _external_kind_from_detail(detail: str) -> ExternalWaitKind | None:
    text = (detail or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            kind = str(payload.get("external_wait_kind") or payload.get("blocker_kind") or "").strip().lower()
            if kind in {"rate_limit", "remote_job", "dependency_unavailable", "other"}:
                return kind
    lowered = text.lower()
    if "rate limit" in lowered or "rate_limit" in lowered:
        return "rate_limit"
    if "remote job" in lowered or "remote_job" in lowered:
        return "remote_job"
    if "dependency" in lowered and "unavail" in lowered:
        return "dependency_unavailable"
    return None


def external_wait_blocker(
    task: Task,
    events: list[TaskEvent] | None = None,
) -> dict[str, Any] | None:
    phase = project_phase(task, events[-1] if events else None)
    if phase != ExecutionPhase.WAITING_EXTERNAL:
        return None
    obs = _observability_blob(task)
    structured = obs.get("external_wait")
    if isinstance(structured, dict):
        kind = str(structured.get("kind") or "").strip().lower()
        if kind in {"rate_limit", "remote_job", "dependency_unavailable", "other"}:
            return {
                "kind": kind,
                "detail": str(structured.get("detail") or "").strip(),
            }
    for blocker in reversed(_compact_state(task).get("blockers") or []):
        if not isinstance(blocker, str):
            continue
        kind = _external_kind_from_detail(blocker)
        if kind:
            return {"kind": kind, "detail": blocker.strip()}
    for event in reversed(events or []):
        kind = _external_kind_from_detail(event.detail or "")
        if kind:
            return {"kind": kind, "detail": (event.detail or "")[:500]}
        if (event.kind or "").lower() in {"external_wait", "waiting_external"}:
            parsed_kind = _external_kind_from_detail(event.title or "")
            return {
                "kind": parsed_kind or "other",
                "detail": (event.title or event.detail or "").strip()[:500],
            }
    return {"kind": "other", "detail": ""}


def linked_decision_inbox_item(task_id: str) -> dict[str, Any] | None:
    try:
        from .coding_workers import load_decision_inbox

        for item in load_decision_inbox(open_only=True):
            if item.task_id == task_id or item.related_task_id == task_id:
                return item.as_dict()
    except Exception:
        return None
    return None


def progress_units(task: Task) -> dict[str, Any] | None:
    obs = _observability_blob(task)
    structured = obs.get("progress")
    if isinstance(structured, dict):
        completed = structured.get("completed_units")
        total = structured.get("total_units")
        unit_type = str(structured.get("unit_type") or "").strip()
        if (
            isinstance(completed, int)
            and isinstance(total, int)
            and total > 0
            and 0 <= completed <= total
            and unit_type
        ):
            return {
                "completed_units": completed,
                "total_units": total,
                "unit_type": unit_type,
            }
    state = _compact_state(task)
    plan = state.get("plan")
    if isinstance(plan, list) and plan:
        total = len(plan)
        completed_steps = state.get("completed_steps")
        if isinstance(completed_steps, list):
            completed = min(len(completed_steps), total)
            return {
                "completed_units": completed,
                "total_units": total,
                "unit_type": "plan_steps",
            }
    return None


def current_activity(task: Task, last_event: TaskEvent | None = None) -> str:
    obs = _observability_blob(task)
    explicit = str(obs.get("current_activity") or "").strip()
    if explicit:
        return explicit[:240]
    action = str(task.current_action or "").strip()
    tool = str(task.current_tool or "").strip()
    if action and not action.lower().startswith("thinking"):
        return action[:240]
    if tool:
        return f"Running {tool}"[:240]
    phase = project_phase(task, last_event)
    if phase == ExecutionPhase.WAITING_APPROVAL:
        payload_raw = task.confirmation_payload or ""
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            title = str(payload.get("title") or payload.get("spoken_prompt") or "").strip()
            name = str(payload.get("name") or "").strip()
            if title:
                return f"Waiting for approval: {title}"[:240]
            if name:
                return f"Waiting for approval: {name}"[:240]
        inbox = linked_decision_inbox_item(task.id)
        if inbox and inbox.get("title"):
            return f"Waiting for approval: {inbox['title']}"[:240]
        return "Waiting for approval"
    if phase == ExecutionPhase.WAITING_EXTERNAL:
        blocker = external_wait_blocker(task, [last_event] if last_event else None)
        if blocker and blocker.get("kind") != "other":
            label = str(blocker["kind"]).replace("_", " ")
            detail = str(blocker.get("detail") or "").strip()
            if detail:
                return f"Waiting ({label}): {detail}"[:240]
            return f"Waiting for external ({label})"[:240]
        return "Waiting for external condition"
    if phase == ExecutionPhase.VERIFYING:
        return "Independent verification"
    if phase == ExecutionPhase.PLANNING:
        return "Planning"
    if phase == ExecutionPhase.GATHERING:
        return "Gathering context"
    if phase == ExecutionPhase.RECOVERING:
        return "Recovering from failure"
    if phase == ExecutionPhase.FINALIZING:
        return "Finalizing result"
    if last_event is not None:
        title = str(last_event.title or "").strip()
        if title and "think" not in title.lower():
            return title[:240]
    return "Working"


def _verification_failed_text(text: str) -> bool:
    lowered = text.lower()
    if not lowered:
        return False
    if re.search(r"\b(fail|failed|failure|not verified|verification failed)\b", lowered):
        return True
    return lowered.startswith("unverified") or "did not pass" in lowered


def _normalize_check(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(row.get("type") or "agent"),
        "target": str(row.get("target") or "task"),
        "result": str(row.get("result") or "unknown").lower(),
        "severity": str(row.get("severity") or "info").lower(),
        "evidence": str(row.get("evidence") or row.get("detail") or "")[:4000],
        **({"remediation": str(row["remediation"])[:2000]} if row.get("remediation") else {}),
    }


def _aggregate_verification_result(
    checks: list[dict[str, Any]],
    *,
    task_status: str,
    stage: str,
    allow_degraded: bool,
) -> str:
    if not checks:
        if task_status == "failed" and stage == "verify":
            return "VERIFICATION_FAILED"
        return "NOT_VERIFIED"
    results = [str(item.get("result") or "").lower() for item in checks]
    if any(result in {"fail", "failed", "error"} for result in results):
        if (
            allow_degraded
            and task_status == "completed"
            and any(result in {"pass", "passed", "ok", "success"} for result in results)
        ):
            return "PARTIALLY_VERIFIED"
        return "VERIFICATION_FAILED"
    if all(result in {"pass", "passed", "ok", "success"} for result in results):
        return "VERIFIED"
    if any(result in {"pass", "passed", "ok", "success"} for result in results):
        return "PARTIALLY_VERIFIED"
    if task_status == "completed":
        return "VERIFIED"
    return "NOT_VERIFIED"


def verification_summary(task: Task) -> dict[str, Any]:
    obs = _observability_blob(task)
    structured = obs.get("verification_summary")
    if isinstance(structured, dict) and structured.get("checks"):
        out = dict(structured)
        out.setdefault("verifier", {"type": "agent", "name": "Jarvis verifier"})
        out.setdefault("evidence_refs", [])
        out.setdefault("warnings", [])
        out.setdefault("timestamp", _iso(task.finished_at))
        out.setdefault("answer_changed_by_verification", bool(out.get("answer_changed_by_verification")))
        if "result" not in out:
            out["result"] = _aggregate_verification_result(
                out.get("checks") or [],
                task_status=str(task.status or ""),
                stage=str(task.stage or "").lower(),
                allow_degraded=True,
            )
        return out

    raw = str(task.verification or "").strip()
    checks: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    warnings: list[str] = []
    answer_changed = bool(obs.get("answer_changed_by_verification"))

    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for row in parsed.get("checks") or []:
                if isinstance(row, dict):
                    checks.append(_normalize_check(row))
            evidence_refs = [str(item) for item in parsed.get("evidence_refs") or [] if str(item).strip()]
            warnings = [str(item) for item in parsed.get("warnings") or [] if str(item).strip()]
            answer_changed = bool(parsed.get("answer_changed_by_verification", answer_changed))
            verifier = parsed.get("verifier")
            if isinstance(verifier, dict):
                verifier_out: Any = verifier
            else:
                verifier_out = {"type": "agent", "name": str(verifier or "Jarvis independent verifier")}
            result = str(parsed.get("result") or "").upper()
            if result not in {"VERIFIED", "VERIFICATION_FAILED", "PARTIALLY_VERIFIED", "NOT_VERIFIED"}:
                result = _aggregate_verification_result(
                    checks,
                    task_status=str(task.status or ""),
                    stage=str(task.stage or "").lower(),
                    allow_degraded=True,
                )
            return {
                "verifier": verifier_out,
                "checks": checks,
                "result": result,
                "evidence_refs": evidence_refs,
                "warnings": warnings,
                "timestamp": _iso(task.finished_at),
                "answer_changed_by_verification": answer_changed,
            }

    if raw:
        passed = not _verification_failed_text(raw)
        checks.append(
            _normalize_check(
                {
                    "type": "agent",
                    "target": "task",
                    "result": "pass" if passed else "fail",
                    "severity": "info" if passed else "error",
                    "evidence": raw,
                }
            )
        )

    result = _aggregate_verification_result(
        checks,
        task_status=str(task.status or ""),
        stage=str(task.stage or "").lower(),
        allow_degraded=True,
    )
    if task.error and result != "VERIFIED":
        warnings.append(str(task.error)[:500])

    verifier_name = "Jarvis independent verifier" if checks else ""
    return {
        "verifier": {"type": "agent", "name": verifier_name} if verifier_name else {"type": "", "name": ""},
        "checks": checks,
        "result": result,
        "evidence_refs": evidence_refs,
        "warnings": warnings,
        "timestamp": _iso(task.finished_at),
        "answer_changed_by_verification": answer_changed,
    }


def project_phase(task: Task, last_event: TaskEvent | None = None) -> ExecutionPhase:
    status = str(task.status or "queued").lower()
    stage = str(task.stage or "queued").lower()
    if task.waiting_for_confirmation:
        return ExecutionPhase.WAITING_APPROVAL
    if status == "queued":
        return ExecutionPhase.QUEUED
    if status == "cancelled":
        return ExecutionPhase.CANCELLED
    if status == "failed":
        if stage == "verify":
            return ExecutionPhase.FAILED
        return ExecutionPhase.FAILED
    if status == "completed":
        summary = verification_summary(task)
        if summary["result"] == "VERIFICATION_FAILED":
            return ExecutionPhase.DEGRADED
        if summary["result"] == "PARTIALLY_VERIFIED":
            return ExecutionPhase.DEGRADED
        return ExecutionPhase.COMPLETED
    if status == "waiting" and not task.waiting_for_confirmation:
        return ExecutionPhase.WAITING_EXTERNAL
    if stage == "verify":
        return ExecutionPhase.VERIFYING
    if stage == "diagnose":
        return ExecutionPhase.RECOVERING
    if stage == "finalize":
        return ExecutionPhase.FINALIZING
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


def phase_stale_threshold_seconds(phase: ExecutionPhase) -> float:
    override = (os.environ.get("JARVIS_PHASE_STALE_SECONDS") or "").strip()
    if override:
        try:
            return max(30.0, float(override))
        except ValueError:
            pass
    return _DEFAULT_STALE_SECONDS.get(phase, 600.0)


def phase_timing(
    task: Task,
    history: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = project_phase(task)
    started_at: str | None = None
    for row in reversed(history):
        if row.get("phase") == current.value and row.get("started_at"):
            started_at = str(row["started_at"])
            break
    if not started_at and task.started_at:
        started_at = _iso(task.started_at)
    phase_elapsed = 0.0
    if started_at:
        try:
            start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            phase_elapsed = max(0.0, (_utc(now or datetime.now(timezone.utc)) - _utc(start_dt)).total_seconds())
        except ValueError:
            phase_elapsed = 0.0
    threshold = phase_stale_threshold_seconds(current)
    stale = (
        current not in TERMINAL_PHASES
        and phase_elapsed >= threshold
        and str(task.status or "") in {"running", "waiting", "queued"}
    )
    return {
        "phase_started_at": started_at,
        "phase_elapsed_seconds": phase_elapsed,
        "stale_phase_warning": stale,
        "stale_phase_threshold_seconds": threshold,
    }


def build_phase_history(task: Task, events: list[TaskEvent]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    current_phase = ExecutionPhase.QUEUED
    segment_start = _iso(task.created_at) or _iso(datetime.now(timezone.utc))
    segment_source = "orchestrator"
    segment_blocking: str | None = None

    def close_segment(ended_at: str | None) -> None:
        nonlocal history
        if history and history[-1].get("phase") == current_phase.value and not history[-1].get("ended_at"):
            history[-1]["ended_at"] = ended_at
            return
        history.append(
            {
                "phase": current_phase.value,
                "task_id": task.id,
                "started_at": segment_start,
                "ended_at": ended_at,
                "source": segment_source,
                "blocking_reason": segment_blocking,
            }
        )

    for event in events:
        hinted = phase_for_event(event)
        resolved = reconcile_projected_phase(current_phase, hinted)
        if resolved == current_phase:
            continue
        event_time = _iso(event.created_at)
        close_segment(event_time)
        current_phase = resolved
        segment_start = event_time or segment_start
        segment_source = str(event.source or "jarvis-agent")
        segment_blocking = None
        if resolved == ExecutionPhase.WAITING_EXTERNAL:
            blocker = _external_kind_from_detail(event.detail or "") or "other"
            segment_blocking = blocker
        if resolved == ExecutionPhase.WAITING_APPROVAL:
            segment_blocking = "approval_required"

    effective = project_phase(task, events[-1] if events else None)
    if effective != current_phase:
        close_segment(_iso(events[-1].created_at) if events else None)
        current_phase = effective
        segment_start = _iso(events[-1].created_at if events else task.updated_at) or segment_start
        segment_source = "orchestrator"
        segment_blocking = None
        if effective == ExecutionPhase.WAITING_APPROVAL:
            segment_blocking = "approval_required"
        elif effective == ExecutionPhase.WAITING_EXTERNAL:
            blocker = external_wait_blocker(task, events)
            segment_blocking = (blocker or {}).get("kind")

    if not history or history[-1].get("phase") != current_phase.value:
        history.append(
            {
                "phase": current_phase.value,
                "task_id": task.id,
                "started_at": segment_start,
                "ended_at": _iso(task.finished_at) if current_phase in TERMINAL_PHASES else None,
                "source": segment_source,
                "blocking_reason": segment_blocking,
            }
        )
    elif current_phase in TERMINAL_PHASES:
        history[-1]["ended_at"] = _iso(task.finished_at)

    return history


def delegation_worker_phase(status: str) -> ExecutionPhase:
    normalized = (status or "").strip().lower()
    if normalized in {"pending", "queued"}:
        return ExecutionPhase.QUEUED
    if normalized == "running":
        return ExecutionPhase.EXECUTING
    if normalized in {"waiting", "blocked"}:
        return ExecutionPhase.WAITING_EXTERNAL
    if normalized == "completed":
        return ExecutionPhase.COMPLETED
    if normalized == "failed":
        return ExecutionPhase.FAILED
    if normalized == "cancelled":
        return ExecutionPhase.CANCELLED
    return ExecutionPhase.EXECUTING


def aggregate_child_execution(children: list[Any]) -> dict[str, Any]:
    """Summarize RFC-0006 delegated workers for parent task rows."""
    if not children:
        return {}
    phases: list[ExecutionPhase] = []
    active = 0
    waiting = 0
    child_rows: list[dict[str, Any]] = []
    for child in children:
        status = str(getattr(child, "status", "") or "")
        phase = delegation_worker_phase(status)
        phases.append(phase)
        if status in {"running", "pending"}:
            active += 1
        if status in {"waiting", "blocked"}:
            waiting += 1
        child_rows.append(
            {
                "id": getattr(child, "id", ""),
                "status": status,
                "execution_phase": phase.value,
            }
        )
    dominant = ExecutionPhase.EXECUTING
    if any(phase == ExecutionPhase.EXECUTING for phase in phases):
        dominant = ExecutionPhase.EXECUTING
    elif waiting and active:
        dominant = ExecutionPhase.EXECUTING
    elif waiting and not active:
        dominant = ExecutionPhase.WAITING_EXTERNAL
    elif any(phase == ExecutionPhase.FAILED for phase in phases):
        dominant = ExecutionPhase.RECOVERING
    return {
        "dominant_phase": dominant.value,
        "active_workers": active,
        "waiting_workers": waiting,
        "child_count": len(children),
        "children": child_rows,
    }


def active_worker(task: Task) -> str:
    state = _compact_state(task)
    worker = state.get("coding_worker")
    if worker:
        return str(worker)
    return f"Jarvis agent · {task.profile or 'balanced'}"


def observability_export(
    task: Task,
    events: list[TaskEvent],
    *,
    children: list[Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    history = build_phase_history(task, events)
    timing = phase_timing(task, history, now=now)
    phase = project_phase(task, events[-1] if events else None)
    payload: dict[str, Any] = {
        "task_id": task.id,
        "execution_phase": phase.value,
        "current_activity": current_activity(task, events[-1] if events else None),
        "current_action": task.current_action,
        "progress": progress_units(task),
        "phase_history": history,
        "verification_summary": verification_summary(task),
        "external_wait": external_wait_blocker(task, events),
        "decision_inbox_item": linked_decision_inbox_item(task.id),
        **timing,
    }
    if children:
        payload["child_execution"] = aggregate_child_execution(children)
    if phase == ExecutionPhase.WAITING_APPROVAL:
        payload["approval"] = {
            "waiting_for_confirmation": bool(task.waiting_for_confirmation),
            "confirmation_payload": task.confirmation_payload,
            "decision_inbox_item_id": (payload.get("decision_inbox_item") or {}).get("id"),
        }
    return payload
