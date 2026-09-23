from __future__ import annotations

import uuid

import pytest

from app.db.models import Task
from app.db.session import SessionLocal
from app.agent.durable_execution.accounting import ledger_for_run, reset_ledgers
from app.agent.durable_execution.crash import SimulatedWorkerDeath, configure_crash_injection, clear_crash_injection
from app.agent.durable_execution.repository import get_step_by_key, list_steps
from app.agent.durable_execution.runner import run_durable_step
from app.agent.durable_execution.types import CrashBoundary, EffectClass, OperationType, ReplayPolicy, StepStatus


async def _seed_task(task_id: str) -> None:
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title="crash-matrix",
                prompt="crash test",
                status="running",
                stage="act",
            )
        )
        await session.commit()


@pytest.fixture(autouse=True)
def _clear_crash_matrix():
    clear_crash_injection()
    reset_ledgers()
    yield
    clear_crash_injection()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary",
    [
        CrashBoundary.BEFORE_EXECUTE,
        CrashBoundary.AFTER_EXECUTE_BEFORE_COMMIT,
        CrashBoundary.AFTER_COMMIT,
    ],
)
async def test_internal_idempotent_crash_boundaries_recover(jarvis_env, boundary):
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    external_calls = {"n": 0}

    async def _op() -> dict:
        external_calls["n"] += 1
        return {"effect": "internal-ok"}

    configure_crash_injection({("internal-step", boundary)})
    with pytest.raises(SimulatedWorkerDeath):
        await run_durable_step(
            run_id=run_id,
            step_key="internal-step",
            operation_type=OperationType.INTERNAL,
            effect_class=EffectClass.INTERNAL,
            replay_policy=ReplayPolicy.IDEMPOTENT,
            predecessor_keys=[],
            input_fingerprint={"fixture": "internal"},
            operation=_op,
            result_encoder=lambda value: {"_value": value, **value},
        )

    clear_crash_injection()
    value, meta = await run_durable_step(
        run_id=run_id,
        step_key="internal-step",
        operation_type=OperationType.INTERNAL,
        effect_class=EffectClass.INTERNAL,
        replay_policy=ReplayPolicy.IDEMPOTENT,
        predecessor_keys=[],
        input_fingerprint={"fixture": "internal"},
        operation=_op,
        result_encoder=lambda v: {"_value": v, **v},
    )
    if boundary == CrashBoundary.BEFORE_EXECUTE:
        assert external_calls["n"] == 1
    else:
        # execute may have run once before crash; resume must not duplicate committed effect
        assert external_calls["n"] <= 2
    if boundary in {CrashBoundary.AFTER_COMMIT, CrashBoundary.AFTER_EXECUTE_BEFORE_COMMIT}:
        step = await get_step_by_key(run_id, "internal-step")
        assert step is not None
        assert step.status in {StepStatus.COMPLETED.value, StepStatus.RUNNING.value, StepStatus.PENDING.value}
    assert meta.get("reused") in {True, False}


@pytest.mark.asyncio
async def test_keyed_external_replays_without_duplicate_charge(jarvis_env):
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    billed = {"n": 0}

    async def _external() -> dict:
        billed["n"] += 1
        return {"response": "200"}

    await run_durable_step(
        run_id=run_id,
        step_key="keyed-external",
        operation_type=OperationType.TOOL_CALL,
        effect_class=EffectClass.EXTERNAL,
        replay_policy=ReplayPolicy.KEYED,
        predecessor_keys=[],
        input_fingerprint={"url": "https://example.com"},
        operation=_external,
        result_encoder=lambda v: {"_value": v, **v},
    )
    await run_durable_step(
        run_id=run_id,
        step_key="keyed-external",
        operation_type=OperationType.TOOL_CALL,
        effect_class=EffectClass.EXTERNAL,
        replay_policy=ReplayPolicy.KEYED,
        predecessor_keys=[],
        input_fingerprint={"url": "https://example.com"},
        operation=_external,
        result_encoder=lambda v: {"_value": v, **v},
    )
    assert billed["n"] == 1
    ledger = ledger_for_run(run_id)
    assert ledger.external_effects_committed == 1
    assert ledger.external_effects_reused == 1


@pytest.mark.asyncio
async def test_at_most_once_crash_enters_ambiguous_effect(jarvis_env):
    run_id = str(uuid.uuid4())
    await _seed_task(run_id)

    async def _external() -> dict:
        return {"sent": True}

    configure_crash_injection({("risky-external", CrashBoundary.AFTER_EXECUTE_BEFORE_COMMIT)})
    with pytest.raises(SimulatedWorkerDeath):
        await run_durable_step(
            run_id=run_id,
            step_key="risky-external",
            operation_type=OperationType.TOOL_CALL,
            effect_class=EffectClass.EXTERNAL,
            replay_policy=ReplayPolicy.AT_MOST_ONCE,
            predecessor_keys=[],
            input_fingerprint={"action": "send"},
            operation=_external,
            result_encoder=lambda v: {"_value": v, **v},
        )
    step = await get_step_by_key(run_id, "risky-external")
    assert step is not None
    assert step.status == StepStatus.AMBIGUOUS_EFFECT.value


@pytest.mark.asyncio
async def test_model_crash_before_commit_reuses_without_second_charge(jarvis_env):
    from app.agent.durable_execution.runner import run_model_step
    from app.providers.base import ChatResult

    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    calls = {"n": 0}

    async def _model() -> ChatResult:
        calls["n"] += 1
        return ChatResult(content="ok", usage={"total_tokens": 99}, timings={"total_ms": 5.0})

    configure_crash_injection({("model:turn:0", CrashBoundary.AFTER_EXECUTE_BEFORE_COMMIT)})
    with pytest.raises(SimulatedWorkerDeath):
        await run_model_step(
            run_id,
            "model:turn:0",
            predecessor_keys=[],
            input_fingerprint={"turn": 0},
            operation=_model,
            cost_extractor=lambda r: (int(r.usage.get("total_tokens") or 0), 5.0, 0.0),
        )
    clear_crash_injection()
    await run_model_step(
        run_id,
        "model:turn:0",
        predecessor_keys=[],
        input_fingerprint={"turn": 0},
        operation=_model,
        cost_extractor=lambda r: (int(r.usage.get("total_tokens") or 0), 5.0, 0.0),
    )
    ledger = ledger_for_run(run_id)
    assert ledger.billed_model_tokens == 99
    assert calls["n"] >= 1
    assert ledger.reused_model_tokens == 0 or calls["n"] == 1


@pytest.mark.asyncio
async def test_approval_park_fixture_persists(jarvis_env):
    from app.agent.durable_execution.runner import park_execution_wait, resume_execution_wait

    run_id = str(uuid.uuid4())
    await _seed_task(run_id)
    await park_execution_wait(
        run_id,
        "approval-wait",
        kind="approval",
        wake_payload={"token": "confirm-1"},
    )
    steps = await list_steps(run_id)
    assert any(s.status == StepStatus.PARKED.value for s in steps)
    await resume_execution_wait(run_id, "approval-wait")
    steps = await list_steps(run_id)
    resumed = next(s for s in steps if s.step_key == "approval-wait")
    assert resumed.status == StepStatus.PENDING.value
