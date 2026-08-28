from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..marketing.audit import get_audit_trail
from ..marketing.evaluation import evaluate_action
from ..marketing.service import MarketingService
from ..marketing.store import reset_marketing_store

router = APIRouter(prefix="/api/amazon-ads", tags=["amazon-ads"])

_service: MarketingService | None = None


def get_service() -> MarketingService:
    global _service
    if _service is None:
        _service = MarketingService()
    return _service


def set_service(service: MarketingService) -> None:
    global _service
    _service = service


class OAuthStartIn(BaseModel):
    label: str
    profile_ids: list[str] = Field(default_factory=list)
    redirect_uri: str = "http://localhost:4780/api/amazon-ads/oauth/callback"


class OAuthCallbackIn(BaseModel):
    connection_id: str
    code: str
    state: str


class IngestIn(BaseModel):
    profile_id: str
    start_date: str
    end_date: str


class ScheduledIngestIn(BaseModel):
    start_date: str
    end_date: str


class PolicyUpdateIn(BaseModel):
    write_authority: str | None = None
    max_bid_change_pct: float | None = None
    max_budget_change_pct: float | None = None
    absolute_daily_spend_ceiling: float | None = None
    protected_entities: list[str] | None = None
    min_evidence_days: int | None = None
    break_even: dict[str, float] | None = None
    acos_threshold: float | None = None
    roas_threshold: float | None = None
    high_spend_no_sale_threshold: float | None = None
    low_conversion_click_threshold: int | None = None
    cpc_change_threshold_pct: float | None = None


class ApproveIn(BaseModel):
    actor: str = "user"


class ExecuteIn(BaseModel):
    actor: str = "user"
    approved: bool = False
    approval_source: str = "manual"


@router.post("/oauth/start")
async def oauth_start(body: OAuthStartIn):
    try:
        return get_service().start_oauth(
            label=body.label,
            profile_ids=body.profile_ids,
            redirect_uri=body.redirect_uri,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/oauth/callback")
async def oauth_callback(body: OAuthCallbackIn):
    try:
        return get_service().complete_oauth(
            connection_id=body.connection_id,
            code=body.code,
            state=body.state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/oauth/refresh/{connection_id}")
async def oauth_refresh(connection_id: str):
    try:
        return get_service().refresh_oauth(connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/oauth/revoke/{connection_id}")
async def oauth_revoke(connection_id: str):
    try:
        return get_service().revoke_oauth(connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/connections")
async def list_connections():
    return {"connections": get_service().list_connections()}


@router.get("/health/{profile_id}")
async def health(profile_id: str):
    return get_service().health(profile_id)


@router.get("/metrics/{profile_id}")
async def metrics(profile_id: str, end_date: str):
    return get_service().metrics(profile_id, end_date=end_date)


@router.get("/recommendations")
async def recommendations(profile_id: str | None = None):
    return {"recommendations": get_service().recommendations(profile_id=profile_id)}


@router.get("/pending-approvals")
async def pending_approvals():
    return {"pending": get_service().pending_approvals()}


@router.get("/winners-waste/{profile_id}")
async def winners_waste(profile_id: str, end_date: str, days: int = 30):
    return get_service().winners_waste(profile_id, end_date=end_date, days=days)


@router.post("/ingest")
async def ingest(body: IngestIn):
    try:
        return get_service().ingest(
            profile_id=body.profile_id,
            start_date=body.start_date,
            end_date=body.end_date,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/ingest/scheduled")
async def ingest_scheduled(body: ScheduledIngestIn):
    return get_service().ingest_scheduled(start_date=body.start_date, end_date=body.end_date)


@router.get("/policy")
async def get_policy():
    return get_service().get_policy()


@router.put("/policy")
async def update_policy(body: PolicyUpdateIn):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return get_service().update_policy(updates)


@router.post("/recommendations/{rec_id}/approve")
async def approve_recommendation(rec_id: str, body: ApproveIn):
    try:
        return get_service().approve_recommendation(rec_id, actor=body.actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/recommendations/{rec_id}/execute")
async def execute_recommendation(rec_id: str, body: ExecuteIn):
    return get_service().execute_recommendation(
        rec_id,
        actor=body.actor,
        approved=body.approved,
        approval_source=body.approval_source,
    )


@router.get("/audit")
async def audit_trail(recommendation_id: str | None = None):
    return {"entries": get_audit_trail(recommendation_id=recommendation_id)}


@router.get("/evaluation/{profile_id}/{recommendation_id}")
async def evaluation(profile_id: str, recommendation_id: str, entity_type: str, entity_id: str):
    return evaluate_action(
        profile_id=profile_id,
        recommendation_id=recommendation_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
