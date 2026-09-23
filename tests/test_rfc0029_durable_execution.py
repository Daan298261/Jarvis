from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import ExecutionAttempt, ExecutionStep, Task
from app.db.session import SessionLocal
from app.execution.accounting import ledger_for_run, reset_ledgers
from app.execution.crash import SimulatedWorkerDeath, configure_crash_injection, clear_crash_injection
from app.execution.recovery import recover_run_state
from app.execution.replay import resolve_tool_replay, stable_idempotency_key
from app.execution.repository import (
    RunNotRecoverable,
    StepBlocked,
    claim_attempt,
    commit_step_result,
    expire_abandoned_attempts,
    last_committed_step_key,
    list_steps,
    upsert_step,
)
from app.execution.runner import park_execution_wait, resume_execution_wait, run_durable_step, run_model_step
from app.execution.types import CrashBoundary, EffectClass, OperationType, ReplayPolicy, StepStatus
from app.providers.base import ChatResult


async def _seed_task(task_id: str, *, status: str = "running") -> None:
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title="RFC-0029",
                prompt="durable test",
                status=status,
                stage="act",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_predecessor_must_commit_before_dependent(jarvis_env):
    reset_ledgers()
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    a = await upsert_step(
        run_id=run_id,
        step_key="step-a",
        predecessor_keys=[],
        operation_type=OperationType.INTERNAL.value,
        effect_class=EffectClass.INTERNAL.value,
        replay_policy=ReplayPolicy.IDEMPOTENT.value,
        input_hash="a",
        idempotency_key="a-key",
    )
    with pytest.raises(StepBlocked):
        await upsert_step(
            run_id=run_id,
            step_key="step-b",
            predecessor_keys=["step-a"],
            operation_type=OperationType.INTERNAL.value,
            effect_class=EffectClass.INTERNAL.value,
            replay_policy=ReplayPolicy.IDEMPOTENT.value,
            input_hash="b",
            idempotency_key="b-key",
        )
    await commit_step_result(a.id, result={"ok": True})
    b = await upsert_step(
        run_id=run_id,
        step_key="step-b",
        predecessor_keys=["step-a"],
        operation_type=OperationType.INTERNAL.value,
        effect_class=EffectClass.INTERNAL.value,
        replay_policy=ReplayPolicy.IDEMPOTENT.value,
        input_hash="b",
        idempotency_key="b-key",
    )
    assert b.step_key == "step-b"


@pytest.mark.asyncio
async def test_model_step_reuse_avoids_double_accounting(jarvis_env):
    reset_ledgers()
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    calls = {"n": 0}

    async def _provider() -> ChatResult:
        calls["n"] += 1
        return ChatResult(content="hello", usage={"total_tokens": 50}, timings={"total_ms": 12.0})

    await run_model_step(
        run_id,
        "model:1",
        predecessor_keys=[],
        input_fingerprint={"turn": 1},
        operation=_provider,
        cost_extractor=lambda r: (
            int(r.usage.get("total_tokens") or 0),
            float(r.timings.get("total_ms") or 0.0),
            0.0,
        ),
    )
    await run_model_step(
        run_id,
        "model:1",
        predecessor_keys=[],
        input_fingerprint={"turn": 1},
        operation=_provider,
        cost_extractor=lambda r: (
            int(r.usage.get("total_tokens") or 0),
            float(r.timings.get("total_ms") or 0.0),
            0.0,
        ),
    )
    assert calls["n"] == 1
    ledger = ledger_for_run(run_id)
    assert ledger.billed_model_tokens == 50
    assert ledger.reused_model_tokens == 50


@pytest.mark.asyncio
async def test_cancelled_run_fail_closed(jarvis_env):
    run_id = str(uuid.uuid4())
    await _seed_task(run_id, status="cancelled")
    with pytest.raises(RunNotRecoverable):
        await upsert_step(
            run_id=run_id,
            step_key="x",
            predecessor_keys=[],
            operation_type=OperationType.TOOL_CALL.value,
            effect_class=EffectClass.INTERNAL.value,
            replay_policy=ReplayPolicy.IDEMPOTENT.value,
            input_hash="x",
            idempotency_key="x",
        )


@pytest.mark.asyncio
async def test_recovery_snapshot_from_persistence(jarvis_env):
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    step = await upsert_step(
        run_id=run_id,
        step_key="persist-me",
        predecessor_keys=[],
        operation_type=OperationType.MODEL_CALL.value,
        effect_class=EffectClass.NONE.value,
        replay_policy=ReplayPolicy.IDEMPOTENT.value,
        input_hash="h",
        idempotency_key="k",
    )
    await commit_step_result(step.id, result={"content": "cached"})
    snap = await recover_run_state(run_id)
    assert snap["recoverable"] is True
    assert "persist-me" in snap["reusable_step_keys"]


@pytest.mark.asyncio
async def test_lease_expiry_allows_new_worker_claim(jarvis_env):
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    step = await upsert_step(
        run_id=run_id,
        step_key="lease-step",
        predecessor_keys=[],
        operation_type=OperationType.INTERNAL.value,
        effect_class=EffectClass.INTERNAL.value,
        replay_policy=ReplayPolicy.IDEMPOTENT.value,
        input_hash="h",
        idempotency_key="k",
    )
    first = await claim_attempt(step.id, "worker-a", lease_seconds=1)
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    async with SessionLocal() as session:
        attempt = await session.get(ExecutionAttempt, first.id)
        assert attempt is not None
        attempt.lease_expires_at = past
        await session.commit()
    abandoned = await expire_abandoned_attempts()
    assert first.id in abandoned
    second = await claim_attempt(step.id, "worker-b", lease_seconds=30)
    assert second.worker_id == "worker-b"
    assert second.id != first.id


@pytest.mark.asyncio
async def test_park_and_resume_persist_wake_condition(jarvis_env):
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    await park_execution_wait(
        run_id,
        "wait-approval",
        kind="approval",
        wake_payload={"confirmation_id": "abc"},
        predecessor_keys=[],
    )
    steps = await list_steps(run_id)
    parked = next(item for item in steps if item.step_key == "wait-approval")
    assert parked.status == StepStatus.PARKED.value
    payload = json.loads(parked.wake_condition_json)
    assert payload["kind"] == "approval"
    await resume_execution_wait(run_id, "wait-approval")
    steps = await list_steps(run_id)
    resumed = next(item for item in steps if item.step_key == "wait-approval")
    assert resumed.status == StepStatus.PENDING.value


@pytest.mark.asyncio
async def test_stable_idempotency_key_and_external_defaults(jarvis_env):
    key1 = stable_idempotency_key("run", "step", "web_fetch", {"url": "https://example.com"})
    key2 = stable_idempotency_key("run", "step", "web_fetch", {"url": "https://example.com"})
    assert key1 == key2
    effect, policy = resolve_tool_replay("web_fetch", None)
    assert effect == EffectClass.EXTERNAL
    assert policy == ReplayPolicy.KEYED
    effect_u, policy_u = resolve_tool_replay("unknown_external", None)
    assert effect_u == EffectClass.INTERNAL
    assert policy_u == ReplayPolicy.IDEMPOTENT


@pytest.mark.asyncio
async def test_last_committed_step_key_ordering(jarvis_env):
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    a = await upsert_step(
        run_id=run_id,
        step_key="a",
        predecessor_keys=[],
        operation_type=OperationType.INTERNAL.value,
        effect_class=EffectClass.INTERNAL.value,
        replay_policy=ReplayPolicy.IDEMPOTENT.value,
        input_hash="1",
        idempotency_key="1",
    )
    await commit_step_result(a.id, result={"n": 1})
    b = await upsert_step(
        run_id=run_id,
        step_key="b",
        predecessor_keys=["a"],
        operation_type=OperationType.INTERNAL.value,
        effect_class=EffectClass.INTERNAL.value,
        replay_policy=ReplayPolicy.IDEMPOTENT.value,
        input_hash="2",
        idempotency_key="2",
    )
    await commit_step_result(b.id, result={"n": 2})
    assert await last_committed_step_key(run_id) == "b"
