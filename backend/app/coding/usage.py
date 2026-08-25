from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import CodingUsageSample, Task
from ..db.session import SessionLocal
from .catalog import CURSOR_MODEL_CATALOG, resolve_model

# USD per million tokens. Local work is free.
_RATES: dict[str, tuple[float, float, float]] = {
    item["id"]: (
        float(item.get("input_usd_per_m") or 0),
        float(item.get("cached_usd_per_m") or 0),
        float(item.get("output_usd_per_m") or 0),
    )
    for item in CURSOR_MODEL_CATALOG
}
_RATES["local-qwen"] = (0.0, 0.0, 0.0)
_RATES["local"] = (0.0, 0.0, 0.0)
_RATES["deterministic"] = (0.0, 0.0, 0.0)


def estimate_cost_usd(
    model: str,
    input_tokens: int = 0,
    cached_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    key = (model or "local-qwen").strip()
    resolved = resolve_model(key)
    rate_key = resolved["id"] if resolved else key
    inp, cached, out = _RATES.get(rate_key, (0.0, 0.0, 0.0))
    cost = (
        (max(0, int(input_tokens)) / 1_000_000) * inp
        + (max(0, int(cached_tokens)) / 1_000_000) * cached
        + (max(0, int(output_tokens)) / 1_000_000) * out
    )
    return round(cost, 6)


async def record_usage(
    *,
    task_id: str = "",
    worker: str,
    model: str,
    task_class: str = "",
    complexity: int = 0,
    input_tokens: int = 0,
    cached_tokens: int = 0,
    output_tokens: int = 0,
    duration_seconds: float = 0,
    verified_success: bool = False,
    first_attempt_success: bool = False,
    retries: int = 0,
    estimated_cost_usd: float | None = None,
) -> CodingUsageSample:
    cost = (
        estimate_cost_usd(model, input_tokens, cached_tokens, output_tokens)
        if estimated_cost_usd is None
        else round(float(estimated_cost_usd), 6)
    )
    row = CodingUsageSample(
        task_id=task_id or "",
        worker=worker,
        model=model,
        task_class=task_class or "",
        complexity=int(complexity or 0),
        input_tokens=int(input_tokens or 0),
        cached_tokens=int(cached_tokens or 0),
        output_tokens=int(output_tokens or 0),
        estimated_cost_usd=cost,
        duration_seconds=float(duration_seconds or 0),
        verified_success=bool(verified_success),
        first_attempt_success=bool(first_attempt_success),
        retries=int(retries or 0),
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def record_task_usage(task_id: str, outcome: str, verified: bool) -> CodingUsageSample | None:
    """Record local-supervisor usage when a software-engineering task finishes."""
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            return None
        task_class = task.task_class or ""
        if task_class != "software engineering":
            return None
        duration = float(task.duration_seconds or 0)
        retries = int(task.retries or 0)
        prompt = task.prompt or ""
        success = outcome == "completed" and verified
    from .routing import estimate_complexity

    return await record_usage(
        task_id=task_id,
        worker="local",
        model="local-qwen",
        task_class=task_class or "software engineering",
        complexity=estimate_complexity(prompt, task_class),
        duration_seconds=duration,
        verified_success=success,
        first_attempt_success=success and retries == 0,
        retries=retries,
        estimated_cost_usd=0.0,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _month_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _as_sample_dict(row: CodingUsageSample) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "worker": row.worker,
        "model": row.model,
        "task_class": row.task_class,
        "complexity": row.complexity,
        "input_tokens": row.input_tokens,
        "cached_tokens": row.cached_tokens,
        "output_tokens": row.output_tokens,
        "estimated_cost_usd": row.estimated_cost_usd,
        "duration_seconds": row.duration_seconds,
        "verified_success": row.verified_success,
        "first_attempt_success": row.first_attempt_success,
        "retries": row.retries,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def usage_summary(limit: int = 50) -> dict[str, Any]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(CodingUsageSample).order_by(CodingUsageSample.id.desc()).limit(limit))
        ).scalars().all()
        all_rows = (await session.execute(select(CodingUsageSample))).scalars().all()

    month = _month_start()
    month_rows = [row for row in all_rows if _aware(row.created_at) and _aware(row.created_at) >= month]
    verified = [row for row in all_rows if row.verified_success]
    month_verified = [row for row in month_rows if row.verified_success]
    total_cost = round(sum(row.estimated_cost_usd for row in all_rows), 6)
    month_cost = round(sum(row.estimated_cost_usd for row in month_rows), 6)
    verified_cost = round(sum(row.estimated_cost_usd for row in verified), 6)
    n_verified = len(verified)
    by_worker: dict[str, dict[str, Any]] = {}
    by_class: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        bucket = by_worker.setdefault(
            row.worker or "unknown",
            {"worker": row.worker, "samples": 0, "verified": 0, "cost_usd": 0.0, "retries": 0},
        )
        bucket["samples"] += 1
        bucket["verified"] += int(row.verified_success)
        bucket["cost_usd"] = round(bucket["cost_usd"] + row.estimated_cost_usd, 6)
        bucket["retries"] += row.retries
        klass = row.task_class or "unclassified"
        cls = by_class.setdefault(
            klass,
            {"task_class": klass, "samples": 0, "verified": 0, "cost_usd": 0.0, "local_verified": 0, "local_samples": 0},
        )
        cls["samples"] += 1
        cls["verified"] += int(row.verified_success)
        cls["cost_usd"] = round(cls["cost_usd"] + row.estimated_cost_usd, 6)
        if row.worker == "local":
            cls["local_samples"] += 1
            cls["local_verified"] += int(row.verified_success)

    for bucket in by_worker.values():
        bucket["success_rate"] = round(bucket["verified"] / bucket["samples"], 3) if bucket["samples"] else None
        bucket["cost_per_verified_success"] = (
            round(bucket["cost_usd"] / bucket["verified"], 6) if bucket["verified"] else None
        )
    for cls in by_class.values():
        cls["success_rate"] = round(cls["verified"] / cls["samples"], 3) if cls["samples"] else None
        cls["local_success_rate"] = (
            round(cls["local_verified"] / cls["local_samples"], 3) if cls["local_samples"] else None
        )
        cls["cost_per_verified_success"] = round(cls["cost_usd"] / cls["verified"], 6) if cls["verified"] else None

    return {
        "primary_metric": "cost_per_verified_successful_software_task",
        "cost_per_verified_success_usd": round(verified_cost / n_verified, 6) if n_verified else None,
        "verified_successes": n_verified,
        "samples": len(all_rows),
        "total_cost_usd": total_cost,
        "month_cost_usd": month_cost,
        "month_verified_successes": len(month_verified),
        "by_worker": sorted(by_worker.values(), key=lambda item: item["worker"]),
        "by_task_class": sorted(by_class.values(), key=lambda item: item["task_class"]),
        "recent": [_as_sample_dict(row) for row in rows],
        "note": "Optimize cost per verified successful software task, not cost per token.",
    }
