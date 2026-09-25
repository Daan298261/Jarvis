from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from ..config import load_settings
from ..perception.commentary import (
    CommentaryDecision,
    CommentaryFeedbackRequest,
    CommentaryPresence,
    SocialCommentaryPolicy,
    publish_comment_intent,
    structured_counts_from_perception_state,
)
from ..perception.commentary_store import CommentaryStateStore
from ..perception.models import ObservationCandidate
from ..perception.store import PerceptionStateStore

router = APIRouter(prefix="/api/perception/commentary", tags=["perception"])
COMMENTARY_STORE = CommentaryStateStore()
PERCEPTION_STORE = PerceptionStateStore()
POLICY = SocialCommentaryPolicy(store=COMMENTARY_STORE)


def presence_from_counts(
    *,
    person_count: int | None,
    person_present: bool | None,
    identity_state: str = "disabled",
    relationship: str | None = None,
    unknown_guest_present: bool = False,
) -> CommentaryPresence:
    count = person_count
    if count is None and person_present:
        count = 1
    if count is None:
        count = 0
    resolved_identity = identity_state
    if resolved_identity == "disabled" and count >= 1:
        resolved_identity = "unknown"
    return CommentaryPresence(
        identity_state=resolved_identity,
        relationship=relationship,
        person_count=count,
        unknown_guest_present=unknown_guest_present or count > 1,
    )


@router.get("/status")
async def commentary_status():
    settings = load_settings().social_commentary
    return SocialCommentaryPolicy(settings=settings, store=COMMENTARY_STORE).status()


@router.get("/recent")
async def commentary_recent(limit: int = 20):
    limit = max(1, min(limit, 48))
    return {"items": POLICY.recent(limit=limit)}


@router.post("/feedback")
async def commentary_feedback(body: CommentaryFeedbackRequest):
    try:
        return POLICY.apply_feedback(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class CommentaryEvaluateRequest(BaseModel):
    """Evaluate a single RFC-0053 candidate through the commentary gate."""

    model_config = ConfigDict(extra="forbid")

    candidate: ObservationCandidate
    person_count: int | None = None
    person_present: bool | None = None
    identity_state: str = "disabled"
    relationship: str | None = None
    unknown_guest_present: bool = False


@router.post("/evaluate", response_model=CommentaryDecision)
async def evaluate_candidate(body: CommentaryEvaluateRequest) -> CommentaryDecision:
    candidate = body.candidate
    presence = presence_from_counts(
        person_count=body.person_count,
        person_present=body.person_present,
        identity_state=body.identity_state,
        relationship=body.relationship,
        unknown_guest_present=body.unknown_guest_present,
    )
    structured = structured_counts_from_perception_state(PERCEPTION_STORE.load(), candidate.fact)
    settings = load_settings().social_commentary
    policy = SocialCommentaryPolicy(settings=settings, store=COMMENTARY_STORE)
    return policy.evaluate(candidate, presence=presence, structured_counts=structured)


async def process_candidates(
    candidates: list[ObservationCandidate],
    *,
    person_count: int | None = None,
    person_present: bool | None = None,
) -> list[CommentaryDecision]:
    if not candidates:
        return []
    settings = load_settings().social_commentary
    if not settings.enabled:
        return []
    policy = SocialCommentaryPolicy(settings=settings, store=COMMENTARY_STORE)
    presence = presence_from_counts(person_count=person_count, person_present=person_present)
    perception_state = PERCEPTION_STORE.load()
    decisions: list[CommentaryDecision] = []
    for candidate in candidates:
        structured = structured_counts_from_perception_state(perception_state, candidate.fact)
        decision = policy.evaluate(candidate, presence=presence, structured_counts=structured)
        decisions.append(decision)
        if decision.outcome == "intent" and decision.intent is not None:
            await publish_comment_intent(decision.intent)
    return decisions
