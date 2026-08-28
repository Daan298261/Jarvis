from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent.advisor import (
    ORCHESTRATOR,
    AdvisorError,
    AdvisorResponse,
    StubAdvisorProvider,
    advisor_has_execution_channel,
)
from ..agent.local_harness import EscalationPolicy, LocalEscalationSignals

router = APIRouter(prefix="/api/advisor", tags=["advisor"])


class PreviewBody(BaseModel):
    goal: str
    task_class: str = "mixed"
    observations: list[str] = Field(default_factory=list)
    failed_approaches: list[str] = Field(default_factory=list)
    unresolved_problem: str = ""
    relevant_files: list[str] = Field(default_factory=list)
    retained_facts: list[str] = Field(default_factory=list)
    consecutive_failures: int = 0
    confidence: float = 1.0
    local_attempts: int = 0
    already_escalated: int = 0
    user_requested: bool = False
    max_cost_usd: float = 0.10
    advisor_cost_usd: float = 0.02


class EscalateBody(BaseModel):
    package_id: str
    provider: str = "stub"
    consecutive_failures: int = 0
    confidence: float = 1.0
    local_attempts: int = 1
    already_escalated: int = 0
    user_requested: bool = False
    max_cost_usd: float = 0.10
    advisor_cost_usd: float = 0.02


def _signals(body: PreviewBody | EscalateBody) -> LocalEscalationSignals:
    return LocalEscalationSignals(
        consecutive_failures=body.consecutive_failures,
        confidence=body.confidence,
        local_attempts=body.local_attempts,
        already_escalated=body.already_escalated,
        user_requested=body.user_requested,
    )


def _policy(body: PreviewBody | EscalateBody) -> EscalationPolicy:
    return EscalationPolicy(
        max_cost_usd=body.max_cost_usd,
        advisor_cost_usd=body.advisor_cost_usd,
    )


def _http_error(exc: AdvisorError) -> HTTPException:
    status = 404 if exc.code == "package_not_found" else 400
    if exc.code == "authority_violation":
        status = 403
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.post("/preview")
async def preview_advisor_context(body: PreviewBody) -> dict[str, Any]:
    """Show exactly what context would leave the local system for an advisor."""
    package = ORCHESTRATOR.preview(
        goal=body.goal,
        task_class=body.task_class,
        observations=body.observations,
        failed_approaches=body.failed_approaches,
        unresolved_problem=body.unresolved_problem,
        relevant_files=body.relevant_files,
        retained_facts=body.retained_facts,
        signals=_signals(body),
        escalation_policy=_policy(body),
        cost_estimate_usd=body.advisor_cost_usd,
    )
    payload = package.as_dict()
    payload["outbound_preview"] = package.outbound_preview()
    return payload


@router.get("/packages/{package_id}")
async def get_advisor_package(package_id: str) -> dict[str, Any]:
    package = ORCHESTRATOR.get_package(package_id)
    if package is None:
        raise HTTPException(404, "Advisor package not found")
    payload = package.as_dict()
    payload["outbound_preview"] = package.outbound_preview()
    return payload


@router.post("/escalate")
async def escalate_to_advisor(body: EscalateBody) -> dict[str, Any]:
    """Escalate a locally stuck task to an advisor under policy and cost limits."""
    provider = StubAdvisorProvider() if body.provider == "stub" else None
    if provider is not None and advisor_has_execution_channel(provider):
        raise _http_error(AdvisorError("provider exposes execution channel", code="authority_violation"))
    try:
        response: AdvisorResponse = await ORCHESTRATOR.escalate(
            body.package_id,
            provider,
            escalation_policy=_policy(body),
            signals=_signals(body),
        )
    except AdvisorError as exc:
        raise _http_error(exc) from exc
    return response.as_dict()
