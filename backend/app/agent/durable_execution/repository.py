from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ...db.models import ExecutionAttempt, ExecutionStep, Task, utcnow
from ...db.session import SessionLocal
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


class InputsChanged(StepBlocked):
    """The step already committed an answer for other inputs; it must never be reused for these ones."""


class StepSuperseded(StepBlocked):
    """This attempt lost the step (its lease lapsed and another attempt took it); its result is discarded."""


async def _lock_step(session, step_id: int, now: datetime) -> None:
    """Open the transaction with a write on the step row, so SQLite grants this connection its write lock
    before anything is read (BEGIN IMMEDIATE semantics). Every check after this, and the writes that
    follow, run as one serialized transaction: a concurrent claim or commit waits for it to finish."""
    locked = await session.execute(update(ExecutionStep).where(ExecutionStep.id == step_id).values(updated_at=now))
    if locked.rowcount == 0:
        raise ValueError(f"step {step_id} missing")


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
    expected_input_hash: str | None = None,
    attempt_id: int | None = None,
) -> ExecutionStep:
    """Commit the step's result. With ``expected_input_hash`` / ``attempt_id`` the commit only lands while
    the step still carries those inputs and that attempt still holds it; the check and the write are one
    locked transaction, so a claim for other inputs can never slip in between them."""
    now = utcnow()
    status = StepStatus.COMPLETED.value if success else StepStatus.FAILED.value
    async with SessionLocal() as session:
        await _lock_step(session, step_id, now)
        step = await session.get(ExecutionStep, step_id)
        if expected_input_hash is not None and step.input_hash != expected_input_hash:
            # Another attempt claimed the step for other inputs after this one's lease lapsed.
            raise StepSuperseded(f"step {step.step_key} now belongs to other inputs; this result is discarded")
        if attempt_id is not None:
            attempt = await session.get(ExecutionAttempt, attempt_id)
            if attempt is None or attempt.status != AttemptStatus.ACTIVE.value:
                raise StepSuperseded(f"step {step.step_key} was taken over by another attempt; this result is discarded")
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


async def claim_attempt(
    step_id: int,
    worker_id: str,
    lease_seconds: int | None = None,
    *,
    input_hash: str | None = None,
    idempotency_key: str | None = None,
) -> ExecutionAttempt:
    """Claim the step's lease. With ``input_hash``, an uncommitted step is re-pointed at those inputs
    in the same transaction, only once no other live attempt holds it (a committed step never is).
    The whole claim is one locked transaction, so two concurrent claims can never both win."""
    now = utcnow()
    lease_until = now + timedelta(seconds=DEFAULT_LEASE_SECONDS if lease_seconds is None else lease_seconds)
    async with SessionLocal() as session:
        await _lock_step(session, step_id, now)
        step = await session.get(
            ExecutionStep,
            step_id,
            options=(selectinload(ExecutionStep.attempts),),
        )

        for attempt in step.attempts:
            if attempt.status != AttemptStatus.ACTIVE.value:
                continue
            expires = _utc(attempt.lease_expires_at)
            if expires and expires > now:
                if attempt.worker_id == worker_id and (input_hash is None or step.input_hash == input_hash):
                    attempt.heartbeat_at = now
                    attempt.lease_expires_at = lease_until
                    await session.commit()
                    await session.refresh(attempt)
                    return attempt
                raise StepBlocked("another attempt holds an active lease")

        if input_hash is not None and step.input_hash != input_hash:
            if step.status == StepStatus.COMPLETED.value:
                raise InputsChanged(f"step {step.step_key} already committed for other inputs")
            step.input_hash = input_hash
            if idempotency_key is not None:
                step.idempotency_key = idempotency_key

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


async def heartbeat_attempt(attempt_id: int, lease_seconds: int | None = None) -> bool:
    """Extend a still-active attempt's lease. Returns False once the attempt no longer holds the step."""
    now = utcnow()
    lease_until = now + timedelta(seconds=DEFAULT_LEASE_SECONDS if lease_seconds is None else lease_seconds)
    async with SessionLocal() as session:
        renewed = await session.execute(
            update(ExecutionAttempt)
            .where(ExecutionAttempt.id == attempt_id, ExecutionAttempt.status == AttemptStatus.ACTIVE.value)
            .values(heartbeat_at=now, lease_expires_at=lease_until)
        )
        await session.commit()
        return renewed.rowcount > 0


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


async def reset_orphaned_in_flight_steps(now: datetime | None = None) -> list[int]:
    """Fail RUNNING/PENDING steps whose worker lease is gone (process crash / force-stop).

    Without this, a killed elevated backend leaves steps mid-flight and the next
    owner task can stall inside durable execution after force_restart.
    """
    now = now or utcnow()
    reset_ids: list[int] = []
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ExecutionStep).where(
                    ExecutionStep.status.in_(
                        [StepStatus.RUNNING.value, StepStatus.PENDING.value]
                    )
                )
            )
        ).scalars().all()
        for step in rows:
            attempts = (
                await session.execute(
                    select(ExecutionAttempt).where(ExecutionAttempt.step_id == step.id)
                )
            ).scalars().all()
            has_live_lease = False
            for attempt in attempts:
                if attempt.status != AttemptStatus.ACTIVE.value:
                    continue
                expires = _utc(attempt.lease_expires_at)
                if expires and expires > now:
                    has_live_lease = True
                    break
            if has_live_lease:
                continue
            step.status = StepStatus.FAILED.value
            step.updated_at = now
            reset_ids.append(step.id)
        await session.commit()
    return reset_ids


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
