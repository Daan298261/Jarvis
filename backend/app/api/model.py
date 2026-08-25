from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent.agent_benchmark import (
    apply_expected_solution,
    check_case,
    format_prompt,
    get_case,
    list_suite,
    prepare_case,
    record_case_result,
    empty_metrics,
)
from ..config import data_dir, load_settings, save_settings
from ..inference.benchmarks import list_benchmarks, record_benchmark_sample, task_outcome_stats
from ..inference.backends import probe_remote_server
from ..inference.harness import load_last_report, run_harness
from ..inference.manager import MANAGER
from ..inference.hardware_gate import hardware_purchase_gate
from ..inference.profiles import available_profiles, declared_profiles

router = APIRouter(prefix="/api/model", tags=["model"])


class LoadBody(BaseModel):
    profile: str | None = None


class HarnessBody(BaseModel):
    live: bool = False
    background: bool = False


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
            "escalation_only": p.name == "expert",
        }
        for p in available_profiles()
    ]
    snapshot["outcomes"] = await task_outcome_stats()
    snapshot["benchmarks"] = await list_benchmarks(limit=12)
    snapshot["harness"] = load_last_report()
    return snapshot


@router.get("/probe")
async def probe_inference():
    settings = load_settings()
    probe = await probe_remote_server(
        settings.inference.host,
        settings.inference.port,
        settings.inference.api_key,
        timeout=8,
    )
    return {
        "backend": settings.inference.backend,
        "host": settings.inference.host,
        "port": settings.inference.port,
        "base_url": f"http://{settings.inference.host}:{settings.inference.port}/v1",
        **probe,
    }


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


@router.get("/harness")
async def model_harness():
    return load_last_report() or {"ran_at": None, "model_available": False, "blocked_reason": "not run yet"}


@router.post("/harness/run")
async def run_model_harness():
    report = await run_harness(
        loaded=MANAGER.state.loaded,
        chat=MANAGER.provider.chat if MANAGER.provider else None,
        refresh_resources=MANAGER.refresh_resources,
        state=MANAGER.state,
        persist=True,
    )
    return report.as_dict()


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


class AgentSuiteRun(BaseModel):
    case_id: str
    simulate_success: bool = False


@router.get("/agent-suite")
async def agent_suite():
    return list_suite()


@router.post("/agent-suite/run")
async def run_agent_suite_case(body: AgentSuiteRun):
    try:
        case = get_case(body.case_id)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown case: {body.case_id}") from exc
    workspace = data_dir() / "agent-suite" / case.id
    ctx = prepare_case(case, workspace)
    if body.simulate_success:
        apply_expected_solution(case, ctx)
    ok, notes = check_case(case, workspace, ctx)
    metrics = empty_metrics()
    metrics["success"] = bool(ok or body.simulate_success)
    metrics["verification_result"] = notes
    await record_case_result(
        case=case,
        metrics=metrics,
        source="simulate" if body.simulate_success else "api",
        workspace=str(workspace),
    )
    return {
        "success": metrics["success"],
        "prompt": format_prompt(case, ctx),
        "notes": notes,
        "case_id": case.id,
        "check_passed": ok,
    }


@router.get("/hardware-gate")
async def hardware_gate():
    return await hardware_purchase_gate()


@router.post("/unload")
async def unload_model():
    await MANAGER.unload()
    settings = load_settings()
    return await MANAGER.snapshot(settings)
