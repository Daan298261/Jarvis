from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.agent.execution_status import (
    ExecutionPhase,
    aggregate_child_execution,
    build_phase_history,
    current_activity,
    external_wait_blocker,
    is_legal_phase_transition,
    observability_export,
    progress_units,
    reconcile_projected_phase,
    verification_summary,
)
from app.db.models import DelegatedWorker, Task, TaskEvent


def _task(**changes) -> Task:
    values = {
        "id": "task-rfc0026",
        "title": "Observability",
        "prompt": "Run work",
        "status": "running",
        "stage": "act",
        "profile": "balanced",
        "created_at": datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc),
    }
    values.update(changes)
    return Task(**values)


def test_legal_transition_rules_reject_terminal_reopen():
    assert is_legal_phase_transition(ExecutionPhase.EXECUTING, ExecutionPhase.VERIFYING)
    assert not is_legal_phase_transition(ExecutionPhase.COMPLETED, ExecutionPhase.EXECUTING)
    assert reconcile_projected_phase(ExecutionPhase.EXECUTING, ExecutionPhase.COMPLETED) == ExecutionPhase.COMPLETED
    assert reconcile_projected_phase(ExecutionPhase.COMPLETED, ExecutionPhase.EXECUTING) == ExecutionPhase.COMPLETED


def test_phase_history_records_source_and_blocking_reason():
    task = _task(status="running", waiting_for_confirmation=True)
    events = [
        TaskEvent(
            task_id=task.id,
            kind="stage",
            stage="plan",
            title="Planning",
            source="jarvis-agent",
            created_at=datetime(2026, 8, 31, 10, 1, tzinfo=timezone.utc),
        ),
        TaskEvent(
            task_id=task.id,
            kind="confirm",
            stage="act",
            title="Confirmation required",
            source="jarvis-agent",
            created_at=datetime(2026, 8, 31, 10, 2, tzinfo=timezone.utc),
        ),
    ]
    history = build_phase_history(task, events)
    assert [row["phase"] for row in history] == ["QUEUED", "PLANNING", "WAITING_APPROVAL"]
    assert history[-1]["phase"] == "WAITING_APPROVAL"
    assert history[-1]["blocking_reason"] == "approval_required"
    assert history[-1]["source"] == "jarvis-agent"


def test_current_activity_prefers_tool_over_generic():
    task = _task(current_action="", current_tool="filesystem")
    assert current_activity(task) == "Running filesystem"
    task = _task(
        waiting_for_confirmation=True,
        confirmation_payload=json.dumps({"title": "Delete /tmp/demo", "name": "filesystem"}),
    )
    assert "Delete /tmp/demo" in current_activity(task)


def test_external_wait_distinguishes_known_blockers():
    task = _task(
        status="waiting",
        compact_memory=json.dumps(
            {
                "observability": {
                    "external_wait": {"kind": "rate_limit", "detail": "Provider throttled requests"},
                }
            }
        ),
    )
    blocker = external_wait_blocker(task, [])
    assert blocker == {"kind": "rate_limit", "detail": "Provider throttled requests"}
    unknown = external_wait_blocker(_task(status="waiting"), [])
    assert unknown == {"kind": "other", "detail": ""}


def test_progress_units_only_when_deterministic():
    task = _task(compact_memory=json.dumps({"plan": ["a", "b", "c"], "completed_steps": ["a"]}))
    progress = progress_units(task)
    assert progress == {"completed_units": 1, "total_units": 3, "unit_type": "plan_steps"}
    assert progress_units(_task()) is None


def test_verification_summary_structured_checks_and_not_verified_success():
    completed = _task(
        status="completed",
        finished_at=datetime(2026, 8, 31, 10, 5, tzinfo=timezone.utc),
        verification="pytest passed",
    )
    summary = verification_summary(completed)
    assert summary["result"] == "VERIFIED"
    assert summary["checks"][0]["type"] == "agent"
    assert summary["checks"][0]["evidence"] == "pytest passed"
    assert summary["verifier"]["name"]

    unverified = _task(status="completed", finished_at=datetime(2026, 8, 31, 10, 5, tzinfo=timezone.utc))
    assert verification_summary(unverified)["result"] == "NOT_VERIFIED"

    failed = _task(
        status="completed",
        verification="verification failed: tests did not pass",
    )
    assert verification_summary(failed)["result"] == "VERIFICATION_FAILED"


def test_child_execution_aggregation_keeps_parent_executing_when_parallel():
    children = [
        DelegatedWorker(
            id="w1",
            parent_task_id="parent",
            task="child-a",
            status="running",
            deadline_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
        ),
        DelegatedWorker(
            id="w2",
            parent_task_id="parent",
            task="child-b",
            status="waiting",
            deadline_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
        ),
    ]
    summary = aggregate_child_execution(children)
    assert summary["dominant_phase"] == "EXECUTING"
    assert summary["active_workers"] == 1
    assert summary["waiting_workers"] == 1


def test_observability_export_includes_audit_fields():
    task = _task(
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    events = [
        TaskEvent(
            task_id=task.id,
            kind="tool",
            stage="act",
            title="Running terminal",
            source="jarvis-agent",
            created_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
    ]
    exported = observability_export(task, events)
    assert exported["execution_phase"] == "EXECUTING"
    assert exported["phase_history"]
    assert exported["verification_summary"]["result"] == "NOT_VERIFIED"
    assert "stale_phase_warning" in exported
