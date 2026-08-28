from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..policy.audit import list_audit_events
from ..policy.authorize import authorize
from ..policy.store import (
  create_profile,
  delete_profile,
  get_platform_policy,
  get_profile,
  list_profiles,
  normalize_policy_from_interview,
  update_platform_policy,
  update_profile,
)
from ..tools.base import RiskLevel

router = APIRouter(prefix="/api/agent-policy", tags=["agent-policy"])


class InterviewAnswersIn(BaseModel):
  mission: str = ""
  success_criteria: str = ""
  tone: str = "professional"
  allowed_channels: list[str] = Field(default_factory=list)
  approval_required_actions: list[str] = Field(default_factory=list)
  budgets: dict[str, Any] = Field(default_factory=dict)
  privacy: dict[str, Any] = Field(default_factory=dict)
  scheduling: dict[str, Any] = Field(default_factory=dict)
  escalation: dict[str, Any] = Field(default_factory=dict)
  hard_prohibitions: list[str] = Field(default_factory=list)
  default_autonomy: str | None = None


class CreateProfileIn(BaseModel):
  name: str
  interview_answers: InterviewAnswersIn
  policy: dict[str, Any] | None = None
  generated_prompt: str | None = None
  actor: str = "api"


class UpdateProfileIn(BaseModel):
  name: str | None = None
  interview_answers: InterviewAnswersIn | None = None
  policy: dict[str, Any] | None = None
  generated_prompt: str | None = None
  actor: str = "api"


class PlatformPolicyIn(BaseModel):
  autonomy_caps: dict[str, str] | None = None
  default_agent_autonomy: str | None = None
  actor: str = "api"


class AuthorizeIn(BaseModel):
  tool_name: str
  action: str | None = None
  risk: str = "medium"
  profile_id: str | None = None
  approved: bool = False


@router.get("")
async def list_agent_policy_profiles():
  return {"profiles": list_profiles()}


@router.post("")
async def create_agent_policy_profile(body: CreateProfileIn):
  interview = body.interview_answers.model_dump()
  return create_profile(
    name=body.name,
    interview_answers=interview,
    policy=body.policy,
    generated_prompt=body.generated_prompt,
    actor=body.actor,
  )


@router.get("/platform")
async def get_platform():
  return get_platform_policy()


@router.put("/platform")
async def put_platform(body: PlatformPolicyIn):
  try:
    return update_platform_policy(
      autonomy_caps=body.autonomy_caps,
      default_agent_autonomy=body.default_agent_autonomy,
      actor=body.actor,
    )
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit")
async def policy_audit(profile_id: str | None = None, limit: int = 100):
  return {"events": list_audit_events(profile_id=profile_id, limit=limit)}


@router.post("/authorize")
async def authorize_tool(body: AuthorizeIn):
  try:
    risk = RiskLevel(body.risk.lower())
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=f"invalid risk: {body.risk}") from exc
  result = authorize(
    body.tool_name,
    action=body.action,
    risk=risk,
    profile_id=body.profile_id,
    approved=body.approved,
  )
  return result.as_dict()


@router.post("/normalize")
async def normalize_interview(body: InterviewAnswersIn):
  interview = body.model_dump()
  return {"policy": normalize_policy_from_interview(interview)}


@router.get("/{profile_id}")
async def get_agent_policy_profile(profile_id: str):
  profile = get_profile(profile_id)
  if not profile:
    raise HTTPException(status_code=404, detail="profile not found")
  return profile


@router.put("/{profile_id}")
async def update_agent_policy_profile(profile_id: str, body: UpdateProfileIn):
  try:
    return update_profile(
      profile_id,
      name=body.name,
      interview_answers=body.interview_answers.model_dump() if body.interview_answers else None,
      policy=body.policy,
      generated_prompt=body.generated_prompt,
      actor=body.actor,
    )
  except KeyError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{profile_id}")
async def delete_agent_policy_profile(profile_id: str, actor: str = "api"):
  try:
    delete_profile(profile_id, actor=actor)
  except KeyError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  return {"ok": True}
