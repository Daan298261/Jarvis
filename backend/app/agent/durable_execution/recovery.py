from __future__ import annotations

import json
from typing import Any

from ...events import BUS
from .repository import (
    AmbiguousEffectError,
    RunNotRecoverable,
    StepBlocked,
    assert_run_recoverable,
    expire_abandoned_attempts,
    get_step_by_key,
    list_steps,
    load_committed_result,
    predecessors_committed,
)
from .types import AttemptStatus, StepStatus


async def reconcile_execution_on_startup() -> dict[str, Any]:
    abandoned = await expire_abandoned_attempts()
    return {"abandoned_attempt_ids": abandoned}


async def recover_run_state(run_id: str) -> dict[str, Any]:
    """Reconstruct durable execution snapshot for a Task run (RFC-0029)."""
    try:
        await assert_run_recoverable(run_id)
    except RunNotRecoverable as exc:
        return {"run_id": run_id, "recoverable": False, "reason": str(exc), "steps": []}

    steps = await list_steps(run_id)
    snapshot: list[dict[str, Any]] = []
    reusable: list[str] = []
    ambiguous: list[str] = []
    parked: list[str] = []
    pending: list[str] = []

    for step in steps:
        item = {
            "step_key": step.step_key,
            "status": step.status,
            "operation_type": step.operation_type,
            "effect_class": step.effect_class,
            "replay_policy": step.replay_policy,
            "committed": step.committed_at is not None,
            "idempotency_key": step.idempotency_key,
        }
        snapshot.append(item)
        if step.status == StepStatus.COMPLETED.value:
            reusable.append(step.step_key)
        elif step.status == StepStatus.AMBIGUOUS_EFFECT.value:
            ambiguous.append(step.step_key)
        elif step.status == StepStatus.PARKED.value:
            parked.append(step.step_key)
        elif step.status in {StepStatus.PENDING.value, StepStatus.RUNNING.value}:
            pending.append(step.step_key)

    return {
        "run_id": run_id,
        "recoverable": True,
        "steps": snapshot,
        "reusable_step_keys": reusable,
        "ambiguous_step_keys": ambiguous,
        "parked_step_keys": parked,
        "pending_step_keys": pending,
    }


async def publish_recovery_event(run_id: str, detail: dict[str, Any]) -> None:
    await BUS.publish(
        run_id,
        "durable_recovery",
        "Execution recovery snapshot",
        json.dumps(detail, default=str)[:8000],
        stage="diagnose",
    )


async def assert_step_runnable(run_id: str, step_key: str, predecessor_keys: list[str]) -> None:
    step = await get_step_by_key(run_id, step_key)
    if step and step.status == StepStatus.AMBIGUOUS_EFFECT.value:
        raise AmbiguousEffectError(f"step {step_key} requires manual reconciliation")
    if step and step.status == StepStatus.COMPLETED.value:
        return
    if not await predecessors_committed(run_id, predecessor_keys):
        raise StepBlocked(f"step {step_key} blocked by uncommitted predecessors")


async def reuse_if_completed(run_id: str, step_key: str) -> dict[str, Any] | None:
    step = await get_step_by_key(run_id, step_key)
    if step is None:
        return None
    if step.status == StepStatus.AMBIGUOUS_EFFECT.value:
        raise AmbiguousEffectError(step_key)
    return await load_committed_result(step)
