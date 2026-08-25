from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..coding.catalog import probe_cursor_models
from ..coding.routing import recommend_worker, recommendation_dict, workers_snapshot
from ..coding.usage import record_usage, usage_summary
from ..config import load_settings

router = APIRouter(prefix="/api/coding", tags=["coding"])


class UsageIn(BaseModel):
    task_id: str = ""
    worker: str
    model: str
    task_class: str = "software engineering"
    complexity: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0
    verified_success: bool = False
    first_attempt_success: bool = False
    retries: int = 0
    estimated_cost_usd: float | None = None


class RouteIn(BaseModel):
    prompt: str
    task_class: str = "software engineering"


@router.get("")
async def coding_overview():
    settings = load_settings()
    summary = await usage_summary()
    return {
        "workers": workers_snapshot(settings),
        "models": probe_cursor_models(settings),
        "usage": summary,
        "coding": settings.coding.model_dump(),
    }


@router.get("/models")
async def coding_models():
    return probe_cursor_models()


@router.get("/usage")
async def coding_usage():
    return await usage_summary()


@router.post("/usage")
async def add_coding_usage(body: UsageIn):
    row = await record_usage(**body.model_dump())
    return {
        "id": row.id,
        "estimated_cost_usd": row.estimated_cost_usd,
        "worker": row.worker,
        "model": row.model,
        "verified_success": row.verified_success,
    }


@router.post("/route")
async def coding_route(body: RouteIn):
    rec = await recommend_worker(body.prompt, body.task_class)
    return recommendation_dict(rec)
