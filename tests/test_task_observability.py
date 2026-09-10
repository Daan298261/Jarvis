from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agent.execution_status import (
    ExecutionPhase,
    active_worker,
    elapsed_seconds,
    normalized_state,
    phase_for_event,
    project_phase,
    verification_summary,
)
from app.db.models import Task, TaskEvent
from app.api.tasks import _iso_utc, _task_dict


def _task(**changes) -> Task:
    values = {
        "id": "task-1",
        "title": "Visible work",
        "prompt": "Do work",
        "status": "running",
        "stage": "act",
        "profile": "balanced",
    }
    values.update(changes)
    return Task(**values)


def test_execution_phase_projects_existing_task_state():
    assert project_phase(_task(status="queued", stage="queued")) == ExecutionPhase.QUEUED
    assert project_phase(_task(stage="verify")) == ExecutionPhase.VERIFYING
    assert project_phase(_task(stage="diagnose")) == ExecutionPhase.RECOVERING
    assert project_phase(_task(status="waiting", waiting_for_confirmation=True)) == ExecutionPhase.WAITING_APPROVAL
    assert project_phase(_task(status="completed")) == ExecutionPhase.COMPLETED
    assert normalized_state(_task(status="cancelled")) == "completed"


def test_event_projection_keeps_phase_history_structured():
    event = TaskEvent(task_id="task-1", kind="tool", stage="act", title="Running filesystem", source="jarvis-agent")
    assert phase_for_event(event) == ExecutionPhase.EXECUTING
    event = TaskEvent(task_id="task-1", kind="confirm", stage="act", title="Confirmation required")
    assert phase_for_event(event) == ExecutionPhase.WAITING_APPROVAL


def test_elapsed_worker_and_verification_summary():
    started = datetime.now(timezone.utc) - timedelta(seconds=12)
    task = _task(
        started_at=started,
        compact_memory='{"coding_worker":"cursor-acp"}',
        status="completed",
        finished_at=started + timedelta(seconds=10),
        verification="pytest passed",
    )
    assert elapsed_seconds(task) == 10
    assert active_worker(task) == "cursor-acp"
    assert verification_summary(task)["result"] == "VERIFIED"


def test_task_api_projection_contains_live_activity_contract():
    task = _task(current_action="Running filesystem", current_tool="filesystem")
    payload = _task_dict(task)
    assert payload["state"] == "running"
    assert payload["execution_phase"] == "EXECUTING"
    assert payload["current_action"] == "Running filesystem"
    assert payload["current_tool"] == "filesystem"
    assert payload["active_worker"].startswith("Jarvis agent")
    assert payload["heartbeat_status"] == "stale"
    assert payload["verification_summary"]["result"] == "NOT_VERIFIED"


def test_naive_sqlite_timestamps_are_serialized_as_utc():
    value = datetime(2026, 8, 31, 11, 0, 0)
    assert _iso_utc(value) == "2026-08-31T11:00:00+00:00"
