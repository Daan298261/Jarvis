from __future__ import annotations

from fastapi import APIRouter

from ..config import load_settings
from ..perception.models import PolicyResult, StructuredObservation
from ..perception.policy import PerceptionPolicy
from ..perception.store import PerceptionStateStore

router = APIRouter(prefix="/api/perception", tags=["perception"])
STORE = PerceptionStateStore()


@router.get("/status")
async def perception_status():
    settings = load_settings().social_perception
    snapshot = STORE.snapshot()
    return {
        "enabled": settings.enabled,
        "semantic_observer": settings.semantic_observer,
        "config": settings.model_dump(),
        **snapshot,
    }


@router.post("/observations", response_model=PolicyResult)
async def ingest_observation(observation: StructuredObservation) -> PolicyResult:
    """Evaluate structured local observations only; this endpoint never accepts image bytes."""
    settings = load_settings().social_perception
    return PerceptionPolicy(settings, STORE).evaluate(observation)


@router.post("/baseline/reset")
async def reset_baseline():
    snapshot = STORE.reset_baseline()
    return {
        "ok": True,
        "baseline_fact_count": len(snapshot.get("baseline") or {}),
    }


@router.post("/state/reset")
async def reset_state():
    snapshot = STORE.reset_state()
    return {
        "ok": True,
        "fact_count": len(snapshot.get("facts") or {}),
        "baseline_fact_count": len(snapshot.get("baseline") or {}),
    }
