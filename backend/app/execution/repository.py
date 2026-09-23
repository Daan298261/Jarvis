from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db.models import ExecutionAttempt, ExecutionStep, Task, utcnow
from ..db.session import SessionLocal
from .types import AttemptStatus, StepStatus, TERMINAL_RUN_STATUSES

DEFAULT_LEASE_SECONDS = 45


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def get_task_status(run_id: str) -> str | None:
    async with SessionLocal() as session:
        task = await session.get(Task, run_id)
        return task.status if task else None


async def assert_run_recoverable(run_id: str) -> None:
    status = await get_task_status(run_id)
    if status is None:
        raise ValueError(f"unknown run {run_id}")
    if status in TERMINAL_RUN_STATUSES:
        raise RunNotRecoverable(f"run {run_id} is terminal ({status})")


class RunNotRecoverable(Exception):
    pass


class StepBlocked(Exception):
    """Predecessor not committed or run is terminal."""


class AmbiguousEffectError(Exception):
    pass


async def get_step_by_key(run_id: str, step_key: str) -> ExecutionStep | None:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(ExecutionStep).where(
                    ExecutionStep.run_id == run_id,
                    ExecutionStep.step_key == step_key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        await session.refresh(row)
        return row


async def list_steps(run_id: str) -> list[ExecutionStep]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ExecutionStep)
                .where(ExecutionStep.run_id == run_id)
                .order_by(ExecutionStep.id)
            )
        ).scalars().all()
        return list(rows)


async def predecessors_committed(run_id: str, predecessor_keys: list[str]) -> bool:
    if not predecessor_keys:
        return True
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ExecutionStep.step_key, ExecutionStep.status, ExecutionStep.committed_at).where(
                    ExecutionStep.run_id == run_id,
                    ExecutionStep.step_key.in_(predecessor_keys),
                )
            )
        ).all()
    found = {key: (status, committed) for key, status, committed in rows}
    for key in predecessor_keys:
        status, committed = found.get(key, (None, None))
        if status != StepStatus.COMPLETED.value or committed is None:
            return False
    return True


async def upsert_step(
    *,
    run_id: str,
    step_key: str,
    predecessor_keys: list[str],
    operation_type: str,
    effect_class: str,
    replay_policy: str,
    input_hash: str,
    idempotency_key: str,
) -> ExecutionStep:
    await assert_run_recoverable(run_id)
    if not await predecessors_committed(run_id, predecessor_keys):
        raise StepBlocked(f"predecessors not committed for {step_key}")

    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(ExecutionStep).where(
                    ExecutionStep.run_id == run_id,
                    ExecutionStep.step_key == step_key,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        step = ExecutionStep(
            run_id=run_id,
            step_key=step_key,
            predecessor_keys_json=json.dumps(predecessor_keys),
            operation_type=operation_type,
            effect_class=effect_class,
            replay_policy=replay_policy,
            status=StepStatus.PENDING.value,
            input_hash=input_hash,
            idempotency_key=idempotency_key,
        )
        session.add(step)
        await session.commit()
        await session.refresh(step)
        return step


async def commit_step_result(
    step_id: int,
    *,
    result: dict[str, Any],
    evidence_ref: str = "",
    cost_tokens: int = 0,
    cost_ms: float = 0.0,
    cost_usd: float = 0.0,
    success: bool = True,
) -> ExecutionStep:
    now = utcnow()
    status = StepStatus.COMPLETED.value if success else StepStatus.FAILED.value
    async with SessionLocal() as session:
        step = await session.get(ExecutionStep, step_id)
        if step is None:
            raise ValueError(f"step {step_id} missing")
        step.status = status
        step.result_json = json.dumps(result, default=str)
        step.evidence_ref = evidence_ref
        step.cost_tokens = cost_tokens
        step.cost_ms = cost_ms
        step.cost_usd = cost_usd
        step.committed_at = now
        step.updated_at = now
        await session.commit()
        await session.refresh(step)
        return step


async def mark_ambiguous_effect(step_id: int, detail: str) -> ExecutionStep:
    async with SessionLocal() as session:
        step = await session.get(ExecutionStep, step_id)
        if step is None:
            raise ValueError(f"step {step_id} missing")
        step.status = StepStatus.AMBIGUOUS_EFFECT.value
        step.result_json = json.dumps({"detail": detail}, default=str)
        step.updated_at = utcnow()
        await session.commit()
        await session.refresh(step)
        return step


async def park_step(step_id: int, wake_condition: dict[str, Any]) -> ExecutionStep:
    async with SessionLocal() as session:
        step = await session.get(ExecutionStep, step_id)
        if step is None:
            raise ValueError(f"step {step_id} missing")
        step.status = StepStatus.PARKED.value
        step.wake_condition_json = json.dumps(wake_condition, default=str)
        step.updated_at = utcnow()
        await session.commit()
        await session.refresh(step)
        return step


async def resume_parked_step(step_id: int) -> ExecutionStep:
    async with SessionLocal() as session:
        step = await session.get(ExecutionStep, step_id)
        if step is None:
            raise ValueError(f"step {step_id} missing")
        if step.status != StepStatus.PARKED.value:
            raise ValueError("step is not parked")
        step.status = StepStatus.PENDING.value
        step.wake_condition_json = ""
        step.updated_at = utcnow()
        await session.commit()
        await session.refresh(step)
        return step


async def mark_step_running(step_id: int) -> None:
    async with SessionLocal() as session:
        step = await session.get(ExecutionStep, step_id)
        if step is None:
            return
        step.status = StepStatus.RUNNING.value
        step.updated_at = utcnow()
        await session.commit()


async def claim_attempt(step_id: int, worker_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> ExecutionAttempt:
    now = utcnow()
    lease_until = now + timedelta(seconds=lease_seconds)
    async with SessionLocal() as session:
        step = await session.get(
            ExecutionStep,
            step_id,
            options=(selectinload(ExecutionStep.attempts),),
        )
        if step is None:
            raise ValueError(f"step {step_id} missing")

        for attempt in step.attempts:
            if attempt.status != AttemptStatus.ACTIVE.value:
                continue
            expires = _utc(attempt.lease_expires_at)
            if expires and expires > now:
                if attempt.worker_id == worker_id:
                    attempt.heartbeat_at = now
                    attempt.lease_expires_at = lease_until
                    await session.commit()
                    await session.refresh(attempt)
                    return attempt
                raise StepBlocked("another worker holds an active lease")

        for attempt in step.attempts:
            if attempt.status == AttemptStatus.ACTIVE.value:
                attempt.status = AttemptStatus.ABANDONED.value
                attempt.finished_at = now

        attempt = ExecutionAttempt(
            step_id=step_id,
            attempt_uuid=str(uuid.uuid4()),
            worker_id=worker_id,
            status=AttemptStatus.ACTIVE.value,
            lease_expires_at=lease_until,
            heartbeat_at=now,
        )
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        return attempt


async def heartbeat_attempt(attempt_id: int, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> None:
    now = utcnow()
    async with SessionLocal() as session:
        attempt = await session.get(ExecutionAttempt, attempt_id)
        if attempt is None or attempt.status != AttemptStatus.ACTIVE.value:
            return
        attempt.heartbeat_at = now
        attempt.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await session.commit()


async def finish_attempt(attempt_id: int, status: AttemptStatus) -> None:
    async with SessionLocal() as session:
        attempt = await session.get(ExecutionAttempt, attempt_id)
        if attempt is None:
            return
        attempt.status = status.value
        attempt.finished_at = utcnow()
        await session.commit()


async def expire_abandoned_attempts(now: datetime | None = None) -> list[int]:
    now = now or utcnow()
    abandoned: list[int] = []
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ExecutionAttempt).where(ExecutionAttempt.status == AttemptStatus.ACTIVE.value)
            )
        ).scalars().all()
        for attempt in rows:
            expires = _utc(attempt.lease_expires_at)
            if expires and expires <= now:
                attempt.status = AttemptStatus.ABANDONED.value
                attempt.finished_at = now
                abandoned.append(attempt.id)
        await session.commit()
    return abandoned


async def last_committed_step_key(run_id: str) -> str | None:
    steps = await list_steps(run_id)
    for step in reversed(steps):
        if step.status == StepStatus.COMPLETED.value and step.committed_at is not None:
            return step.step_key
    return None


async def load_committed_result(step: ExecutionStep) -> dict[str, Any] | None:
    if step.status != StepStatus.COMPLETED.value or not step.committed_at:
        return None
    if not step.result_json:
        return None
    try:
        parsed = json.loads(step.result_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None
