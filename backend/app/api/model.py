from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent.agent_benchmark import TaskMetrics, build_report, list_suite, record_result, suite_coverage
from ..config import load_settings, save_settings
from ..hardware import detect_hardware
from ..inference.benchmarks import list_benchmarks, record_benchmark_sample, task_outcome_stats
from ..inference.hardware_gate import evaluate_purchase_gate
from ..inference.manager import MANAGER
from ..inference.profiles import available_profiles

router = APIRouter(prefix="/api/model", tags=["model"])


class LoadBody(BaseModel):
    profile: str | None = None


class AgentResultBody(BaseModel):
    task_id: str
    profile: str = ""
    success: bool = False
    human_intervention: bool = False
    total_seconds: float = 0
    model_seconds: float = 0
    tool_seconds: float = 0
    model_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    schema_errors: int = 0
    incorrect_actions: int = 0
    verification: str = ""
    notes: str = ""


@router.get("")
async def model_status():
    settings = load_settings()
    snapshot = await MANAGER.snapshot(settings)
    snapshot["profiles"] = [
        {
            "name": p.name,
            "label": p.label,
            "quant": p.quant,
            "thinking": p.thinking,
            "context_size": p.context_size,
            "description": p.description,
        }
        for p in available_profiles()
    ]
    snapshot["outcomes"] = await task_outcome_stats()
    snapshot["benchmarks"] = await list_benchmarks(limit=12)
    snapshot["agent_suite"] = suite_coverage()
    return snapshot


@router.get("/benchmarks")
async def model_benchmarks(limit: int = 50):
    outcomes = await task_outcome_stats()
    return {"outcomes": outcomes, "samples": await list_benchmarks(limit=limit)}


@router.post("/benchmarks/snapshot")
async def capture_benchmark():
    settings = load_settings()
    await MANAGER.refresh_resources()
    state = MANAGER.state
    row = await record_benchmark_sample(
        profile=state.profile or settings.inference.profile,
        quantization=state.quant,
        context_size=state.context_size,
        prompt_tps=state.prompt_tps,
        generation_tps=state.generation_tps,
        vram_used_mib=state.vram_used_mib,
        ram_used_gb=state.ram_used_gb,
        load_time_seconds=state.load_time_seconds,
        source="snapshot",
    )
    return {"ok": True, "sample": None if row is None else {
        "id": row.id,
        "tokens_per_second": row.generation_tps,
        "prompt_tokens_per_second": row.prompt_tps,
        "vram_used_mib": row.vram_used_mib,
        "task_success_rate": row.task_success_rate,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }}


@router.post("/load")
async def load_model(body: LoadBody | None = None):
    settings = load_settings()
    profile = (body.profile if body else None) or settings.inference.profile
    try:
        await MANAGER.load(settings, profile)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if body and body.profile:
        settings.inference.profile = body.profile
        save_settings(settings)
    return await MANAGER.snapshot(settings)


@router.post("/unload")
async def unload_model():
    await MANAGER.unload()
    settings = load_settings()
    return await MANAGER.snapshot(settings)


@router.get("/agent-benchmarks")
async def agent_benchmarks():
    return await build_report()


@router.get("/agent-benchmarks/suite")
async def agent_benchmark_suite():
    return {"tasks": list_suite(), "coverage": suite_coverage()}


@router.post("/agent-benchmarks/results")
async def record_agent_benchmark(body: AgentResultBody):
    spec_ok = any(item["id"] == body.task_id for item in list_suite())
    if not spec_ok:
        raise HTTPException(404, f"Unknown suite task {body.task_id}")
    row = await record_result(TaskMetrics(**body.model_dump()))
    return {"ok": True, "id": row.id, "report": await build_report()}


@router.get("/hardware-gate")
async def hardware_gate():
    report = await build_report()
    samples = await list_benchmarks(limit=50)
    return evaluate_purchase_gate(
        hardware=detect_hardware(),
        inference_samples=samples,
        agent_results=report["results"],
    )
