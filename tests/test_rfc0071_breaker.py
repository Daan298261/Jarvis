from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.automation.audit import list_breaker_audit
from app.automation.breaker import (
    BREAKER_ACTIVE,
    BREAKER_DEGRADED,
    BREAKER_DISABLED_BY_FAILURE,
    admit_automatic_trigger,
    bind_run_to_task,
    ensure_automation,
    finalize_run_outcome,
    get_automation_breaker,
    normalize_task_terminal,
    on_task_terminal,
    reenable_automation,
    reset_automation_breaker_store,
    set_failure_threshold,
)
from app.automation.ids import automation_actor_id, schedule_automation_id
from app.automation.outcomes import TerminalOutcome
from app.auth import generate_private_key
from app.config import load_settings
from app.main import app


@pytest.fixture
def breaker_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.automation.breaker.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.automation.audit.data_dir", lambda: jarvis_env["tmp"])
    reset_automation_breaker_store()
    yield jarvis_env["tmp"]
    reset_automation_breaker_store()


def _fail_run(automation_id: str, run_id: str, n: int = 1) -> None:
    for _ in range(n):
        admit_automatic_trigger(automation_id, run_id=f"{run_id}-{_}", trigger="test")
        finalize_run_outcome(automation_id, f"{run_id}-{_}", TerminalOutcome.FAILURE, summary="boom")


def _audit_types(automation_id: str) -> list[str]:
    return [event["event_type"] for event in list_breaker_audit(automation_id=automation_id, limit=200)]


def _owner_client(monkeypatch) -> tuple[TestClient, str]:
    key = generate_private_key()
    settings = load_settings()
    settings.auth_token = key
    monkeypatch.setattr("app.config.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)
    return TestClient(app), key


def test_repeated_failures_persist_across_reload(breaker_env):
    automation_id = "schedule:sched-1"
    ensure_automation(automation_id, failure_threshold=3)
    _fail_run(automation_id, "r", 2)
    mid = get_automation_breaker(automation_id)
    assert mid is not None
    assert mid.consecutive_failure_count == 2
    assert mid.breaker_state == BREAKER_DEGRADED

    reloaded = get_automation_breaker(automation_id)
    assert reloaded is not None
    assert reloaded.consecutive_failure_count == 2

    finalize_run_outcome(automation_id, "r-2", TerminalOutcome.FAILURE, summary="third")
    tripped = get_automation_breaker(automation_id)
    assert tripped is not None
    assert tripped.breaker_state == BREAKER_DISABLED_BY_FAILURE
    assert tripped.disabled_at
    assert "breaker_tripped" in _audit_types(automation_id)


def test_verified_success_resets_counter(breaker_env):
    automation_id = "schedule:sched-2"
    ensure_automation(automation_id, failure_threshold=3)
    _fail_run(automation_id, "a", 2)
    assert get_automation_breaker(automation_id).consecutive_failure_count == 2

    run_id = "success-run"
    admit_automatic_trigger(automation_id, run_id=run_id, trigger="test")
    finalize_run_outcome(automation_id, run_id, TerminalOutcome.SUCCESS, task_id="task-ok")
    record = get_automation_breaker(automation_id)
    assert record.consecutive_failure_count == 0
    assert record.breaker_state == BREAKER_ACTIVE
    assert "failure_counter_reset" in _audit_types(automation_id)


def test_concurrent_triggers_at_threshold_boundary(breaker_env):
    automation_id = "schedule:sched-3"
    ensure_automation(automation_id, failure_threshold=2)
    _fail_run(automation_id, "pre", 1)
    assert get_automation_breaker(automation_id).breaker_state == BREAKER_DEGRADED

    results: list[bool] = []

    def attempt(idx: int) -> None:
        admission = admit_automatic_trigger(automation_id, run_id=f"boundary-{idx}", trigger="schedule")
        results.append(admission.allowed)
        if admission.allowed:
            finalize_run_outcome(automation_id, f"boundary-{idx}", TerminalOutcome.FAILURE, summary="x")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(attempt, range(8)))

    record = get_automation_breaker(automation_id)
    assert record.breaker_state == BREAKER_DISABLED_BY_FAILURE
    assert record.consecutive_failure_count >= 2
    allowed = [item for item in results if item]
    suppressed = [item for item in results if not item]
    # One failure away from trip: at most one admit past the remaining budget.
    assert len(allowed) <= 1
    assert suppressed, "expected later triggers to be suppressed once disabled"
    assert "breaker_tripped" in _audit_types(automation_id)
    assert "trigger_suppressed" in _audit_types(automation_id)


def test_one_terminal_outcome_per_run_retries(breaker_env):
    automation_id = "schedule:sched-4"
    ensure_automation(automation_id, failure_threshold=5)
    run_id = "single-run"
    admit_automatic_trigger(automation_id, run_id=run_id, trigger="test")
    bind_run_to_task(run_id, "task-retry")

    for _ in range(3):
        finalize_run_outcome(automation_id, run_id, TerminalOutcome.FAILURE, summary="retry", task_id="task-retry")

    record = get_automation_breaker(automation_id)
    assert record.consecutive_failure_count == 1


def test_non_failure_outcomes_do_not_trip(breaker_env):
    automation_id = "schedule:sched-5"
    ensure_automation(automation_id, failure_threshold=3)

    for outcome in (
        TerminalOutcome.CANCELLED,
        TerminalOutcome.SKIPPED,
        TerminalOutcome.DUPLICATE_SUPPRESSED,
        TerminalOutcome.APPROVAL_WAIT,
    ):
        run_id = f"neutral-{outcome.value}"
        admit_automatic_trigger(automation_id, run_id=run_id, trigger="test")
        finalize_run_outcome(automation_id, run_id, outcome)

    record = get_automation_breaker(automation_id)
    assert record.consecutive_failure_count == 0
    assert record.breaker_state == BREAKER_ACTIVE

    assert normalize_task_terminal(status="cancelled") is TerminalOutcome.CANCELLED
    assert normalize_task_terminal(status="completed", verification="checked") is TerminalOutcome.SUCCESS
    assert normalize_task_terminal(status="completed", verification="") is TerminalOutcome.NO_OP


def test_disabled_blocks_admission(breaker_env):
    automation_id = schedule_automation_id("mobile-1")
    ensure_automation(automation_id, failure_threshold=1)
    admit_automatic_trigger(automation_id, run_id="trip", trigger="schedule")
    finalize_run_outcome(automation_id, "trip", TerminalOutcome.FAILURE, summary="down")

    blocked = admit_automatic_trigger(automation_id, run_id="after", trigger="schedule")
    assert not blocked.allowed
    assert blocked.suppressed
    types = _audit_types(automation_id)
    assert "breaker_tripped" in types
    assert "trigger_suppressed" in types


def test_unauthorized_self_reenable_blocked(breaker_env):
    automation_id = "schedule:self"
    ensure_automation(automation_id, failure_threshold=1)
    finalize_run_outcome(automation_id, "r1", TerminalOutcome.FAILURE, summary="fail")
    with pytest.raises(Exception) as exc:
        reenable_automation(automation_id, actor=automation_actor_id(automation_id))
    assert "cannot re-enable itself" in str(exc.value)


def test_operator_reenable_recovery(breaker_env, monkeypatch):
    automation_id = "schedule:recover"
    ensure_automation(automation_id, failure_threshold=1)
    finalize_run_outcome(automation_id, "r1", TerminalOutcome.FAILURE, summary="fail")
    assert get_automation_breaker(automation_id).breaker_state == BREAKER_DISABLED_BY_FAILURE

    recovered = reenable_automation(automation_id, actor="owner")
    assert recovered.breaker_state == BREAKER_ACTIVE
    assert recovered.consecutive_failure_count == 0
    assert recovered.disabled_at is None

    again = reenable_automation(automation_id, actor="owner")
    assert again.breaker_state == BREAKER_ACTIVE

    admission = admit_automatic_trigger(automation_id, run_id="after-reenable", trigger="schedule")
    assert admission.allowed

    types = _audit_types(automation_id)
    assert "reenable" in types
    assert "reenable_idempotent" in types


def test_task_hook_links_binding(breaker_env):
    automation_id = schedule_automation_id("hook-1")
    run_id = "run-hook"
    ensure_automation(automation_id)
    admit_automatic_trigger(automation_id, run_id=run_id, trigger="schedule")
    bind_run_to_task(run_id, "task-hook-1")

    on_task_terminal("task-hook-1", status="failed", error="worker error")
    record = get_automation_breaker(automation_id)
    assert record.consecutive_failure_count == 1
    assert "task-hook-1" in record.recent_failed_run_ids


def test_api_reenable_requires_owner_key(breaker_env, monkeypatch):
    client, key = _owner_client(monkeypatch)

    automation_id = "schedule:api"
    ensure_automation(automation_id, failure_threshold=1)
    finalize_run_outcome(automation_id, "x", TerminalOutcome.FAILURE)

    denied = client.post(f"/api/automation-breaker/{automation_id}/reenable", json={"actor": "owner"})
    assert denied.status_code == 401

    ok = client.post(
        f"/api/automation-breaker/{automation_id}/reenable",
        json={"actor": "owner"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert ok.status_code == 200
    assert ok.json()["breaker_state"] == BREAKER_ACTIVE

    self_actor = client.post(
        f"/api/automation-breaker/{automation_id}/reenable",
        json={"actor": automation_actor_id(automation_id)},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert self_actor.status_code == 403


def test_api_get_list_detail_audit_require_owner_key(breaker_env, monkeypatch):
    client, key = _owner_client(monkeypatch)
    automation_id = "schedule:get-gate"
    ensure_automation(automation_id, kind="schedule", failure_threshold=2)
    finalize_run_outcome(automation_id, "g1", TerminalOutcome.FAILURE, summary="x")

    for path in (
        "/api/automation-breaker",
        f"/api/automation-breaker/{automation_id}",
        "/api/automation-breaker/audit",
        f"/api/automation-breaker/audit?automation_id={automation_id}",
    ):
        denied = client.get(path)
        assert denied.status_code == 401, path

    headers = {"Authorization": f"Bearer {key}"}
    listed = client.get("/api/automation-breaker", headers=headers)
    assert listed.status_code == 200
    assert any(row["automation_id"] == automation_id for row in listed.json()["automations"])

    detail = client.get(f"/api/automation-breaker/{automation_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["automation_id"] == automation_id
    assert detail.json()["kind"] == "schedule"

    audit = client.get(
        f"/api/automation-breaker/audit?automation_id={automation_id}",
        headers=headers,
    )
    assert audit.status_code == 200
    assert isinstance(audit.json()["events"], list)


def test_threshold_and_admission_preserve_kind(breaker_env, monkeypatch):
    automation_id = "schedule:kind-preserve"
    ensure_automation(automation_id, kind="schedule", failure_threshold=3)
    assert get_automation_breaker(automation_id).kind == "schedule"

    # Admission without kind must not rewrite to generic.
    admit_automatic_trigger(automation_id, run_id="kind-admit", trigger="schedule")
    assert get_automation_breaker(automation_id).kind == "schedule"

    # Threshold helper (same path as owner PUT) must preserve kind.
    set_failure_threshold(automation_id, 5, actor="owner")
    assert get_automation_breaker(automation_id).kind == "schedule"
    assert get_automation_breaker(automation_id).failure_threshold == 5
    assert "threshold_updated" in _audit_types(automation_id)

    client, key = _owner_client(monkeypatch)
    via_api = client.put(
        f"/api/automation-breaker/{automation_id}/threshold",
        json={"failure_threshold": 4},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert via_api.status_code == 200
    assert via_api.json()["kind"] == "schedule"
    assert via_api.json()["failure_threshold"] == 4


def test_admission_race_disables_before_new_run(breaker_env):
    """At most one admit past the remaining failure budget; then fail closed."""
    automation_id = "schedule:race"
    ensure_automation(automation_id, failure_threshold=2)
    _fail_run(automation_id, "pre", 1)  # one away from trip
    barrier = threading.Barrier(4)

    def worker(run_id: str) -> bool:
        barrier.wait()
        admission = admit_automatic_trigger(automation_id, run_id=run_id, trigger="schedule")
        if admission.allowed:
            finalize_run_outcome(automation_id, run_id, TerminalOutcome.FAILURE, summary="f")
        return admission.allowed

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, f"race-{i}") for i in range(4)]
        allowed = [f.result() for f in futures]

    record = get_automation_breaker(automation_id)
    assert record.breaker_state == BREAKER_DISABLED_BY_FAILURE
    # Real invariant: only one run may be admitted past the threshold boundary.
    assert sum(1 for item in allowed if item) <= 1
    assert sum(1 for item in allowed if item) == 1

    # After trip, further automatic triggers stay suppressed.
    blocked = admit_automatic_trigger(automation_id, run_id="post-trip", trigger="schedule")
    assert not blocked.allowed
    assert blocked.suppressed

    types = _audit_types(automation_id)
    assert "breaker_tripped" in types
    assert "trigger_suppressed" in types
