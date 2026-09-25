"""Owner/admin approval gates for Skill Forge. No automatic publication."""

from __future__ import annotations

from typing import Any

from .schema import LifecycleStatus, SkillCandidate
from .store import get_candidate, save_candidate, utc_now


class ApprovalError(PermissionError):
    pass


def request_approval(candidate: SkillCandidate, *, actor: str = "skill_forge") -> SkillCandidate:
    """Open a Decision Inbox item and mark candidate as awaiting owner approval.

    Does not activate the skill. Publication requires explicit approve_candidate().
    """
    if candidate.status not in {LifecycleStatus.VERIFIED, LifecycleStatus.APPROVED}:
        raise ApprovalError(
            f"candidate {candidate.candidate_id} must be verified before approval request "
            f"(status={candidate.status.value})"
        )

    inbox_id: str | None = None
    try:
        from ..agent.coding_workers import add_decision_inbox_item

        item = add_decision_inbox_item(
            kind="skill_forge_activation",
            title=f"Approve skill: {candidate.version.manifest.name}",
            detail=(
                f"Skill Forge candidate {candidate.candidate_id} version "
                f"{candidate.version.version_id} passed verification and awaits owner/admin approval. "
                f"Purpose: {candidate.version.manifest.purpose[:300]}"
            ),
            task_id=candidate.candidate_id,
            related_task_id=candidate.skill_id,
        )
        inbox_id = item.id
    except Exception:
        # Decision Inbox may be unavailable in minimal test contexts; still require explicit API approval.
        inbox_id = None

    updated = candidate.model_copy(deep=True)
    updated.decision_inbox_item_id = inbox_id
    updated.updated_at = utc_now()
    updated.version.approval = {
        "requested": True,
        "requested_at": utc_now(),
        "requested_by": actor,
        "decision_inbox_item_id": inbox_id,
        "approved": False,
    }
    return save_candidate(updated)


def approve_candidate(
    candidate_id: str,
    *,
    actor: str,
    admin: bool = False,
) -> SkillCandidate:
    """Record explicit owner/admin approval. Does not auto-activate — forge.activate does."""
    if not actor or not str(actor).strip():
        raise ApprovalError("owner/admin actor is required for skill approval")
    if not admin and actor.strip().lower() not in {"owner", "admin", "taco", "daan"}:
        # Allow any non-empty actor when callers assert admin=True; otherwise require known owner roles.
        # Tests and API pass admin=True for authenticated owner routes.
        raise ApprovalError("skill approval requires owner/admin authority")

    candidate = get_candidate(candidate_id)
    if candidate is None:
        raise ApprovalError(f"candidate not found: {candidate_id}")
    if candidate.status not in {
        LifecycleStatus.VERIFIED,
        LifecycleStatus.APPROVED,
        LifecycleStatus.QUARANTINED,
    }:
        raise ApprovalError(
            f"candidate {candidate_id} cannot be approved from status {candidate.status.value}"
        )

    updated = candidate.model_copy(deep=True)
    updated.status = LifecycleStatus.APPROVED
    updated.version.status = LifecycleStatus.APPROVED
    approval = dict(updated.version.approval or {})
    approval.update(
        {
            "approved": True,
            "approved_at": utc_now(),
            "approved_by": actor.strip(),
            "admin": bool(admin),
        }
    )
    updated.version.approval = approval
    updated.updated_at = utc_now()
    return save_candidate(updated)


def reject_candidate(candidate_id: str, *, actor: str, reason: str) -> SkillCandidate:
    if not actor or not str(actor).strip():
        raise ApprovalError("actor is required to reject a skill candidate")
    candidate = get_candidate(candidate_id)
    if candidate is None:
        raise ApprovalError(f"candidate not found: {candidate_id}")
    updated = candidate.model_copy(deep=True)
    updated.status = LifecycleStatus.REJECTED
    updated.version.status = LifecycleStatus.REJECTED
    updated.rejection_reason = reason or "rejected"
    updated.updated_at = utc_now()
    updated.version.approval = {
        **dict(updated.version.approval or {}),
        "approved": False,
        "rejected_at": utc_now(),
        "rejected_by": actor.strip(),
        "reason": reason,
    }
    return save_candidate(updated)


def approval_snapshot(candidate: SkillCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "status": candidate.status.value,
        "approval": dict(candidate.version.approval or {}),
        "decision_inbox_item_id": candidate.decision_inbox_item_id,
    }
