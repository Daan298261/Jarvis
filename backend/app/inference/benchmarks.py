from __future__ import annotations

from datetime import timezone
from typing import Any

from sqlalchemy import func, select

from ..db.models import BenchmarkSample, Task, utcnow
from ..db.session import SessionLocal


def _sample_dict(row: BenchmarkSample) -> dict[str, Any]:
    return {
        "id": row.id,
        "profile": row.profile,
        "quantization": row.quantization,
        "context_size": row.context_size,
        "prompt_tokens_per_second": row.prompt_tps,
        "tokens_per_second": row.generation_tps,
        "vram_used_mib": row.vram_used_mib,
        "ram_used_gb": row.ram_used_gb,
        "load_time_seconds": row.load_time_seconds,
        "task_success_rate": row.task_success_rate,
        "tasks_completed": row.tasks_completed,
        "tasks_failed": row.tasks_failed,
        "source": row.source,
        "notes": row.notes or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def task_outcome_stats() -> dict[str, Any]:
    async with SessionLocal() as session:
        completed = (
            await session.execute(select(func.count()).select_from(Task).where(Task.status == "completed"))
        ).scalar_one()
        failed = (
            await session.execute(select(func.count()).select_from(Task).where(Task.status == "failed"))
        ).scalar_one()
    finished = int(completed or 0) + int(failed or 0)
    rate = round(int(completed or 0) / finished, 4) if finished else None
    return {
        "tasks_completed": int(completed or 0),
        "tasks_failed": int(failed or 0),
        "task_success_rate": rate,
    }


async def record_benchmark_sample(
    *,
    profile: str = "",
    quantization: str = "",
    context_size: int = 0,
    prompt_tps: float | None = None,
    generation_tps: float | None = None,
    vram_used_mib: int | None = None,
    ram_used_gb: float | None = None,
    load_time_seconds: float | None = None,
    source: str = "timing",
    notes: str = "",
) -> BenchmarkSample | None:
    stats = await task_outcome_stats()
    async with SessionLocal() as session:
        latest = (
            await session.execute(select(BenchmarkSample).order_by(BenchmarkSample.id.desc()).limit(1))
        ).scalar_one_or_none()
        if latest and source == "timing":
            same = (
                latest.profile == (profile or "")
                and latest.quantization == (quantization or "")
                and latest.generation_tps == generation_tps
                and latest.prompt_tps == prompt_tps
                and latest.vram_used_mib == vram_used_mib
            )
            age = 999.0
            if latest.created_at:
                latest_at = latest.created_at
                if latest_at.tzinfo is None:
                    latest_at = latest_at.replace(tzinfo=timezone.utc)
                age = (utcnow() - latest_at).total_seconds()
            if same and age < 15:
                return latest
        row = BenchmarkSample(
            profile=profile or "",
            quantization=quantization or "",
            context_size=int(context_size or 0),
            prompt_tps=prompt_tps,
            generation_tps=generation_tps,
            vram_used_mib=vram_used_mib,
            ram_used_gb=ram_used_gb,
            load_time_seconds=load_time_seconds,
            task_success_rate=stats["task_success_rate"],
            tasks_completed=stats["tasks_completed"],
            tasks_failed=stats["tasks_failed"],
            source=source,
            notes=notes or "",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def list_benchmarks(limit: int = 50) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(BenchmarkSample).order_by(BenchmarkSample.created_at.desc()).limit(limit))
        ).scalars().all()
    return [_sample_dict(row) for row in rows]
