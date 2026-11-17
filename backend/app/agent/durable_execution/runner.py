from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ...events import BUS
from ...tools.registry import REGISTRY
from .accounting import ledger_for_run
from .crash import SimulatedWorkerDeath, check_crash_boundary
from ...providers.base import ChatResult
from .recovery import reuse_if_completed
from .replay import (
    ambiguous_after_crash,
    resolve_tool_replay,
    stable_idempotency_key,
)
from .repository import (
    AmbiguousEffectError,
    InputsChanged,
    StepSuperseded,
    assert_run_recoverable,
    claim_attempt,
    commit_step_result,
    finish_attempt,
    get_step_by_key,
    heartbeat_attempt,
    mark_ambiguous_effect,
    mark_step_running,
    park_step,
    resume_parked_step,
    upsert_step,
)
from .types import AttemptStatus, CrashBoundary, EffectClass, OperationType, ReplayPolicy, StepStatus

T = TypeVar("T")

log = logging.getLogger("jarvis.durable.runner")

_worker_id = f"jarvis-worker-{os.getpid()}"


def set_worker_id(worker_id: str) -> None:
    global _worker_id
    _worker_id = worker_id


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _emit_step_event(
    run_id: str,
    title: str,
    detail: dict[str, Any],
    *,
    kind: str = "durable_step",
) -> None:
    await BUS.publish(
        run_id,
        kind,
        title,
        json.dumps(detail, default=str)[:4000],
        stage="act",
        persist=True,
    )


# Why a restarted task stopped when it finds an answer it already saved for an earlier version of its
# context. The loop adds the action for the surface the owner reads it on (model_inputs_changed_reason).
MODEL_INPUTS_CHANGED = (
    "This task was interrupted, and its conversation changed before it restarted, so it can't safely resume "
    "from the answer it saved earlier."
)

# How often a running step renews its lease (DEFAULT_LEASE_SECONDS = 45), so a model call that runs for
# minutes (chat_call_max_ms) keeps the step and a second runner cannot take it over mid-call. Each renewal
# waits at most HEARTBEAT_BUSY_TIMEOUT_MS for another writer's lock: two failed renewals in a row
# (2 x (15 s + 5 s) = 40 s) still end inside the lease.
HEARTBEAT_INTERVAL_S = 15.0
HEARTBEAT_BUSY_TIMEOUT_MS = 5000


async def _keep_lease(attempt_id: int) -> None:
    """Renew until the attempt loses the step. A failed renewal (lock wait ran out, disk error) is logged
    and retried on the next tick; it never ends the heartbeat or reaches the step's result."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        try:
            if not await heartbeat_attempt(attempt_id, busy_timeout_ms=HEARTBEAT_BUSY_TIMEOUT_MS):
                return
        except Exception:
            log.warning("lease heartbeat for attempt %s failed; retrying next interval", attempt_id, exc_info=True)


async def run_durable_step(
    *,
    run_id: str,
    step_key: str,
    operation_type: OperationType,
    effect_class: EffectClass,
    replay_policy: ReplayPolicy,
    predecessor_keys: list[str] | None,
    input_fingerprint: Any,
    operation: Callable[[], Awaitable[T]],
    result_encoder: Callable[[T], dict[str, Any]],
    cost_extractor: Callable[[T], tuple[int, float, float]] | None = None,
    worker_id: str | None = None,
) -> tuple[T, dict[str, Any]]:
    """Execute one durable step with crash-safe commit ordering."""
    worker = worker_id or _worker_id
    predecessors = list(predecessor_keys or [])
    input_hash = _hash_payload(input_fingerprint)
    idempotency_key = stable_idempotency_key(run_id, step_key, operation_type.value, {"hash": input_hash})

    await assert_run_recoverable(run_id)

    model_call = operation_type == OperationType.MODEL_CALL
    if model_call:
        existing = await get_step_by_key(run_id, step_key)
        if existing is not None and existing.input_hash != input_hash and existing.status == StepStatus.COMPLETED.value:
            # A committed answer for other inputs must never be reused for these ones (RFC-0243). A step
            # that never committed is re-pointed at the new inputs under its lease (claim_attempt) and re-run.
            raise InputsChanged(MODEL_INPUTS_CHANGED)

    reused = await reuse_if_completed(run_id, step_key)
    if reused is not None:
        ledger = ledger_for_run(run_id)
        if operation_type == OperationType.MODEL_CALL:
            ledger.bill_model(
                int(reused.get("cost_tokens") or 0),
                float(reused.get("cost_ms") or 0),
                reused=True,
            )
        elif effect_class == EffectClass.EXTERNAL:
            ledger.bill_external(reused=True)
        await _emit_step_event(
            run_id,
            "Reused completed step",
            {"step_key": step_key, "reused": True, "status": StepStatus.COMPLETED.value},
            kind="step_reused",
        )
        # Reconstruct return value from persisted payload
        inner = reused.get("_value", reused)
        return inner, {"reused": True, "step_key": step_key}

    step = await upsert_step(
        run_id=run_id,
        step_key=step_key,
        predecessor_keys=predecessors,
        operation_type=operation_type.value,
        effect_class=effect_class.value,
        replay_policy=replay_policy.value,
        input_hash=input_hash,
        idempotency_key=idempotency_key,
    )

    if step.status == StepStatus.AMBIGUOUS_EFFECT.value:
        raise AmbiguousEffectError(step_key)

    try:
        attempt = await claim_attempt(
            step.id,
            worker,
            input_hash=input_hash if model_call else None,
            idempotency_key=idempotency_key if model_call else None,
        )
    except InputsChanged as exc:
        raise InputsChanged(MODEL_INPUTS_CHANGED) from exc
    await mark_step_running(step.id)
    check_crash_boundary(step_key, CrashBoundary.BEFORE_EXECUTE)

    executed_value: T | None = None
    crash_before_commit = False
    lease = asyncio.create_task(_keep_lease(attempt.id))
    try:
        executed_value = await operation()
        check_crash_boundary(step_key, CrashBoundary.AFTER_EXECUTE_BEFORE_COMMIT)
    except SimulatedWorkerDeath:
        if ambiguous_after_crash(effect_class, replay_policy):
            await mark_ambiguous_effect(
                step.id,
                "worker died after external effect may have executed; manual reconciliation required",
            )
            await finish_attempt(attempt.id, AttemptStatus.ABANDONED)
            await _emit_step_event(
                run_id,
                "Ambiguous external effect",
                {"step_key": step_key, "status": StepStatus.AMBIGUOUS_EFFECT.value},
                kind="ambiguous_effect",
            )
        crash_before_commit = True
        raise
    except Exception:
        await finish_attempt(attempt.id, AttemptStatus.ABANDONED)
        raise
    finally:
        lease.cancel()
        # Wait for the heartbeat to stop without taking on its outcome: nothing it does may replace the
        # operation's result or exception (the commit's attempt check decides who owns the step).
        await asyncio.wait([lease])
        if not lease.cancelled() and lease.exception() is not None:
            log.warning("lease heartbeat for attempt %s ended with an error", attempt.id, exc_info=lease.exception())

    tokens, ms, usd = (0, 0.0, 0.0)
    if cost_extractor and executed_value is not None:
        tokens, ms, usd = cost_extractor(executed_value)

    encoded = result_encoder(executed_value)  # type: ignore[arg-type]
    encoded["cost_tokens"] = tokens
    encoded["cost_ms"] = ms
    encoded["cost_usd"] = usd

    try:
        committed = await commit_step_result(
            step.id,
            result=encoded,
            cost_tokens=tokens,
            cost_ms=ms,
            cost_usd=usd,
            success=True,
            expected_input_hash=input_hash if model_call else None,
            attempt_id=attempt.id if model_call else None,
        )
    except StepSuperseded:
        await finish_attempt(attempt.id, AttemptStatus.SUPERSEDED)
        raise
    check_crash_boundary(step_key, CrashBoundary.AFTER_COMMIT)
    await finish_attempt(attempt.id, AttemptStatus.COMPLETED)

    ledger = ledger_for_run(run_id)
    if operation_type == OperationType.MODEL_CALL:
        ledger.bill_model(tokens, ms, reused=False)
    elif effect_class == EffectClass.EXTERNAL:
        ledger.bill_external(reused=False)

    await _emit_step_event(
        run_id,
        "Committed execution step",
        {
            "step_key": step_key,
            "step_id": committed.id,
            "attempt_id": attempt.attempt_uuid,
            "status": committed.status,
            "replay_policy": replay_policy.value,
        },
    )
    return executed_value, {"reused": False, "step_key": step_key, "attempt_id": attempt.attempt_uuid}


async def run_model_step(
    run_id: str,
    step_key: str,
    *,
    predecessor_keys: list[str] | None,
    input_fingerprint: Any,
    operation: Callable[[], Awaitable[ChatResult]],
    cost_extractor: Callable[[ChatResult], tuple[int, float, float]] | None = None,
) -> ChatResult:
    def _encode(result: ChatResult) -> dict[str, Any]:
        return {
            "_value": {
                "content": result.content,
                "reasoning": result.reasoning,
                "tool_calls": result.tool_calls,
                "usage": result.usage,
                "timings": result.timings,
            }
        }

    value, meta = await run_durable_step(
        run_id=run_id,
        step_key=step_key,
        operation_type=OperationType.MODEL_CALL,
        effect_class=EffectClass.NONE,
        replay_policy=ReplayPolicy.IDEMPOTENT,
        predecessor_keys=predecessor_keys,
        input_fingerprint=input_fingerprint,
        operation=operation,
        result_encoder=_encode,
        cost_extractor=cost_extractor,
    )
    if meta.get("reused"):
        cached = await reuse_if_completed(run_id, step_key)
        payload = (cached or {}).get("_value") if cached else value
        if isinstance(payload, dict):
            return ChatResult(
                content=str(payload.get("content") or ""),
                reasoning=str(payload.get("reasoning") or ""),
                tool_calls=list(payload.get("tool_calls") or []),
                usage=dict(payload.get("usage") or {}),
                timings=dict(payload.get("timings") or {}),
            )
    if isinstance(value, ChatResult):
        return value
    if isinstance(value, dict):
        return ChatResult(
            content=str(value.get("content") or ""),
            reasoning=str(value.get("reasoning") or ""),
            tool_calls=list(value.get("tool_calls") or []),
            usage=dict(value.get("usage") or {}),
            timings=dict(value.get("timings") or {}),
        )
    return ChatResult(content=str(value))


async def run_tool_step(
    run_id: str,
    step_key: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    predecessor_keys: list[str] | None,
    operation: Callable[[], Awaitable[tuple[str, str | None, bool, str]]],
) -> tuple[str, str | None]:
    """Wrap a tool call. Operation returns (text, attach, success, error)."""
    tool = REGISTRY.tools.get(tool_name)
    effect, policy = resolve_tool_replay(tool_name, tool)

    async def _op() -> tuple[str, str | None, bool, str]:
        return await operation()

    def _encode(result: tuple[str, str | None, bool, str]) -> dict[str, Any]:
        text, attach, success, error = result
        return {
            "_value": text,
            "text": text,
            "attach": attach,
            "success": success,
            "error": error,
            "tool": tool_name,
        }

    value, meta = await run_durable_step(
        run_id=run_id,
        step_key=step_key,
        operation_type=OperationType.TOOL_CALL,
        effect_class=effect,
        replay_policy=policy,
        predecessor_keys=predecessor_keys,
        input_fingerprint={"tool": tool_name, "args": arguments},
        operation=_op,
        result_encoder=_encode,
    )
    if meta.get("reused"):
        cached = await reuse_if_completed(run_id, step_key)
        if cached:
            return str(cached.get("text") or cached.get("_value") or ""), cached.get("attach")
    if isinstance(value, tuple):
        text, attach, _, _ = value
        return text, attach
    return str(value), None


async def park_execution_wait(
    run_id: str,
    step_key: str,
    *,
    kind: str,
    wake_payload: dict[str, Any],
    predecessor_keys: list[str] | None = None,
) -> None:
    step = await upsert_step(
        run_id=run_id,
        step_key=step_key,
        predecessor_keys=list(predecessor_keys or []),
        operation_type=OperationType.PARK.value,
        effect_class=EffectClass.NONE.value,
        replay_policy=ReplayPolicy.IDEMPOTENT.value,
        input_hash=_hash_payload(wake_payload),
        idempotency_key=str(uuid.uuid4()),
    )
    await park_step(step.id, {"kind": kind, **wake_payload})


async def resume_execution_wait(run_id: str, step_key: str) -> None:
    from .repository import get_step_by_key

    step = await get_step_by_key(run_id, step_key)
    if step is None:
        raise ValueError("unknown step")
    await resume_parked_step(step.id)


def last_committed_step_key(run_id: str, step_keys: list[str]) -> str | None:
    """Return the last step_key in order that should gate the next step."""
    return step_keys[-1] if step_keys else None
