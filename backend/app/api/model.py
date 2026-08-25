from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import load_settings, save_settings
from ..inference.benchmarks import recent_benchmarks, record_benchmark
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
            "family": getattr(p, "family", "official"),
            "alias": getattr(p, "alias", "Qwen3.5-9B-Abliterated"),
        }
        for p in available_profiles()
    ]
    return snapshot


@router.get("/benchmarks")
async def model_benchmarks(limit: int = 50):
    return {"samples": recent_benchmarks(min(max(1, limit), 40))}


@router.post("/benchmarks/snapshot")
async def capture_benchmark():
    settings = load_settings()
    await MANAGER.refresh_resources()
    state = MANAGER.state
    sample = record_benchmark(
        profile=state.profile or settings.inference.profile,
        quant=state.quant,
        context_size=state.context_size,
        prompt_tokens_per_second=state.prompt_tps,
        tokens_per_second=state.generation_tps,
        vram_used_mib=state.vram_used_mib,
        ram_used_gb=state.ram_used_gb,
        load_time_seconds=state.load_time_seconds,
        source="snapshot",
    )
    return {"ok": True, "sample": sample}


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


@router.post("/benchmark")
async def run_benchmark():
    settings = load_settings()
    try:
        return await MANAGER.run_benchmark(settings)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))
