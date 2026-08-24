from sqlalchemy import select

from app.db.models import BenchmarkSample, Task
from app.db.session import SessionLocal
from app.inference.benchmarks import list_benchmarks, record_benchmark_sample, task_outcome_stats
from app.inference.manager import MANAGER


async def test_record_timings_persists_benchmark_sample(jarvis_env):
    MANAGER.state.profile = "balanced"
    MANAGER.state.quant = "Q4_K_M"
    MANAGER.state.context_size = 32768
    MANAGER.state.vram_used_mib = 1024
    await MANAGER.record_timings({"predicted_per_second": 18.5, "prompt_per_second": 90.0})
    assert MANAGER.state.generation_tps == 18.5
    samples = await list_benchmarks()
    assert samples
    assert samples[0]["tokens_per_second"] == 18.5
    assert samples[0]["prompt_tokens_per_second"] == 90.0
    assert samples[0]["profile"] == "balanced"
    async with SessionLocal() as session:
        assert (await session.execute(select(BenchmarkSample))).scalars().first() is not None


async def test_task_success_rate_is_included_in_snapshot(jarvis_env):
    async with SessionLocal() as session:
        session.add(Task(id="ok-1", title="a", prompt="a", status="completed"))
        session.add(Task(id="ok-2", title="b", prompt="b", status="completed"))
        session.add(Task(id="bad-1", title="c", prompt="c", status="failed"))
        await session.commit()
    row = await record_benchmark_sample(profile="fast", generation_tps=12.0, source="snapshot")
    assert row is not None
    assert row.tasks_completed == 2
    assert row.tasks_failed == 1
    assert row.task_success_rate == 0.6667
    stats = await task_outcome_stats()
    assert stats["tasks_completed"] == 2
    assert stats["task_success_rate"] == 0.6667
