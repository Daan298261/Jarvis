"""RFC-0116 decision-tier Settings + probe API. Never echoes TypeSafe secrets."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..decision.audit import list_events
from ..decision.jev_client import reset_http_post, using_labeled_fixture
from ..decision.tier import bind_typesafe_key, probe_jev, resolve_status, set_decision_tier, set_notify_requested
from ..licensing.inference import InferenceCredentialError

router = APIRouter(prefix="/api/decision", tags=["decision"])


class DecisionTierIn(BaseModel):
    tier: Literal["local", "jev_optional", "jev_plus"]


class TypesafeKeyIn(BaseModel):
    secret: str = Field(min_length=1, max_length=4000)
    label: str = Field(default="TypeSafe Jev", max_length=120)


@router.get("/jev")
async def jev_status() -> dict[str, Any]:
    return resolve_status()


@router.put("/jev")
async def jev_update(body: DecisionTierIn) -> dict[str, Any]:
    try:
        set_decision_tier(body.tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return resolve_status()


@router.post("/jev/notify")
async def jev_notify() -> dict[str, Any]:
    stamp = set_notify_requested()
    status = resolve_status()
    return {**status, "notify_requested_at": stamp, "jev_availability": status["jev_availability"]}


@router.post("/jev/credentials")
async def jev_bind_key(body: TypesafeKeyIn) -> dict[str, Any]:
    try:
        record = bind_typesafe_key(body.secret, label=body.label)
    except InferenceCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    probed = probe_jev()
    return {
        "credential": {"id": record.get("id"), "provider": record.get("provider"), "label": record.get("label")},
        "status": probed,
    }


@router.post("/jev/probe")
async def jev_probe() -> dict[str, Any]:
    return probe_jev()


@router.get("/jev/audit")
async def jev_audit(limit: int = 40) -> dict[str, Any]:
    return {"events": list_events(limit=limit), "fixture": using_labeled_fixture()}


@router.post("/jev/reset-fixture")
async def jev_reset_fixture() -> dict[str, Any]:
    """Labeled fixtures are process-local; this clears a test double without claiming live success."""
    reset_http_post()
    return {"ok": True, "fixture": using_labeled_fixture()}
