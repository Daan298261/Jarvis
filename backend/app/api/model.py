from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent.agent_benchmark import (
    apply_expected_solution,
    check_case,
    format_prompt,
    get_case,
    list_results as list_agent_results,
    list_suite,
    prepare_case,
    record_case_result,
    empty_metrics,
)
from ..config import data_dir, load_settings, save_settings
from ..inference.benchmarks import list_benchmarks, record_benchmark_sample, task_outcome_stats
from ..inference.hardware_gate import hardware_purchase_gate
from ..inference.manager import MANAGER
from ..inference.profiles import available_profiles

router = APIRouter(prefix="/api/model", tags=["model"])


class LoadBody(BaseModel):
    profile: str | None = None


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


@router.get("/hardware-gate")
async def model_hardware_gate():
    return await hardware_purchase_gate()


@router.get("/agent-suite")
async def model_agent_suite():
    payload = list_suite()
    payload["recent_results"] = await list_agent_results(limit=50)
    return payload


class AgentSuiteRunBody(BaseModel):
    case_id: str
    simulate_success: bool = False


@router.post("/agent-suite/run")
async def run_agent_suite_case(body: AgentSuiteRunBody):
    """Prepare a suite case (and optionally mark a simulated fixture success).

    Live model execution remains a Windows desktop job. This endpoint is the
    dataset/harness path used by tests and the Model page.
    """
    try:
        case = get_case(body.case_id)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown case {body.case_id}") from exc
    workspace = data_dir() / "agent-suite" / case.id
    ctx = prepare_case(case, workspace)
    if body.simulate_success:
        apply_expected_solution(case, ctx)
    ok, note = check_case(case, workspace, ctx)
    metrics = empty_metrics()
    metrics["success"] = ok
    metrics["verification_result"] = note
    settings = load_settings()
    row = await record_case_result(
        case=case,
        metrics=metrics,
        profile=settings.inference.profile,
        source="simulate" if body.simulate_success else "fixture",
        workspace=str(workspace),
        notes=note,
    )
    return {
        "ok": True,
        "case": case.as_public_dict(),
        "prompt": format_prompt(case, ctx),
        "success": ok,
        "note": note,
        "workspace": str(workspace),
        "result_id": row.id,
    }


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
