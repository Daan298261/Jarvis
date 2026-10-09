"""Action gate: RFC-0002 auth → RFC-0027 firewall → RFC-0031 reversibility.

Optional Laya harm veto may only cancel after the hard gates allow; it cannot
grant authority or satisfy ApprovalGrant. Destructive paths still require a
real ApprovalGrant (model confirmed=true never counts).
"""

from __future__ import annotations

import logging
from typing import Any

from ..decision.reflex import decide
from ..security.red_scenarios import HARM as HARM_QUESTION
from ..tools.base import RiskLevel
from .authorize import AuthorizationResult
from .reversibility_gate import SideEffectDecision, evaluate_side_effect

log = logging.getLogger("jarvis.policy.action_gate")

# Live Laya harm-veto on CPU is typically ~100–150 ms once warm. The previous
# 80 ms budget expired before Laya could answer, so every allow fell through to
# generative fallback and metrics never showed provider=laya.
HARM_VETO_DEADLINE_MS = 500.0


def _as_cancel(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"cancel", "yes", "true", "harm"}:
            return True
        if lowered in {"allow", "no", "false", "safe"}:
            return False
        return None
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if score >= 0.7:
        return True
    if score <= 0.3:
        return False
    return None


def _to_authorization(decision: SideEffectDecision) -> AuthorizationResult:
    """Compatibility shim for callers that still expect AuthorizationResult."""
    level = decision.effective_level
    if level is None and decision.authorization is not None:
        level = decision.authorization.effective_level
    if level is None:
        from .levels import AutonomyLevel

        level = AutonomyLevel.L1_SUGGEST_ONLY
    return AuthorizationResult(
        allowed=decision.allowed,
        requires_approval=decision.requires_approval,
        reason=decision.reason,
        effective_level=level,
        capability=decision.capability or (
            decision.authorization.capability if decision.authorization else ""
        ),
    )


def gate_side_effect(
    tool_name: str,
    *,
    action: str | None = None,
    arguments: dict[str, Any] | None = None,
    risk: RiskLevel = RiskLevel.MEDIUM,
    profile_id: str | None = None,
    grant_id: str | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    step_key: str | None = None,
    park_if_needed: bool = True,
    # Legacy: ignored for grant creation. Real grants use grant_id / ApprovalGrant store.
    approved: bool = False,
) -> SideEffectDecision:
    """Primary RFC-0031 entry. ``approved`` alone never creates a grant."""
    del approved  # cannot satisfy human gate — use grant_id from ApprovalGrant
    decision = evaluate_side_effect(
        tool_name,
        action=action,
        arguments=arguments,
        risk=risk,
        profile_id=profile_id,
        grant_id=grant_id,
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        step_key=step_key,
        park_if_needed=park_if_needed,
    )
    if not decision.allowed:
        return decision

    # Optional Laya cancel-only pass. Never grants; never bypasses ApprovalGrant.
    args = arguments or {}
    command = str(args.get("command") or "") if isinstance(args, dict) else ""
    state = {
        "user_message": f"{tool_name} {action or ''} {command or args}".strip()[:800],
        "tool_name": tool_name,
        "action": action or "",
        "destructive": decision.effect.destructive_effect,
    }
    try:
        reflex = decide(state, [HARM_QUESTION], "harm_veto", HARM_VETO_DEADLINE_MS, "local_only")
        answer = reflex.answers.get("cancel")
        cancel = _as_cancel(answer.value) if answer is not None else None
    except Exception as exc:  # noqa: BLE001
        log.debug("harm veto unavailable after allow: %s", exc)
        cancel = None

    if cancel is True:
        return SideEffectDecision(
            allowed=False,
            requires_approval=False,
            reason=f"Laya cancelled this {tool_name} step.",
            effect=decision.effect,
            authorization=decision.authorization,
            firewall=decision.firewall,
            action_id=decision.action_id,
            grant_id=decision.grant_id,
            self_confirm_attempt=decision.self_confirm_attempt,
            effective_level=decision.effective_level,
            capability=decision.capability,
            audit={**decision.audit, "outcome": "laya_cancel"},
        )
    return decision


def gate_tool_call(
    tool_name: str,
    *,
    action: str | None = None,
    arguments: dict[str, Any] | None = None,
    risk: RiskLevel = RiskLevel.MEDIUM,
    profile_id: str | None = None,
    approved: bool = False,
    grant_id: str | None = None,
    task_id: str | None = None,
) -> AuthorizationResult:
    """Backward-compatible wrapper returning AuthorizationResult."""
    # Legacy approved=True from confirm_task is NOT an ApprovalGrant. Callers that
    # still pass approved=True after a real human confirm_task must also supply
    # grant_id. When approved=True without grant_id (legacy resume path), we park
    # with park_if_needed=False and treat it as a trusted resume only when the
    # caller explicitly sets grant_id. For legacy confirm_task, loop creates a grant.
    decision = gate_side_effect(
        tool_name,
        action=action,
        arguments=arguments,
        risk=risk,
        profile_id=profile_id,
        grant_id=grant_id,
        task_id=task_id,
        park_if_needed=not bool(grant_id),
        approved=approved,
    )
    return _to_authorization(decision)
