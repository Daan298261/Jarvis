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
from ..inference.profiles import declared_profiles, profile_as_dict

router = APIRouter(prefix="/api/model", tags=["model"])


class LoadBody(BaseModel):
    profile: str | None = None


class HarnessBody(BaseModel):
    live: bool = False


@router.get("")
async def model_status():
    settings = load_settings()
    snapshot = await MANAGER.snapshot(settings)
    if "profiles" not in snapshot:
        snapshot["profiles"] = [profile_as_dict(p) for p in declared_profiles()]
    snapshot["outcomes"] = await task_outcome_stats()
    snapshot["benchmarks"] = await list_benchmarks(limit=12)
    snapshot["harness_cases"] = list(HARNESS_CASES)
    snapshot["primary_metric"] = "successful autonomous tasks per wall-clock minute"
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
