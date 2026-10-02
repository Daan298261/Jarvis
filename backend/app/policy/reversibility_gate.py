"""RFC-0031 reversibility-first side-effect gate.

Ordering (mandatory):
  1. Ordinary authorization (RFC-0002)
  2. SemanticActionFirewall (RFC-0027 hook)
  3. Reversibility handling / ApprovalGrant / undo registration

Reversibility must never convert a policy or firewall deny into allow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..tools.base import RiskLevel
from .approval_grant import (
    action_id_for,
    park_approval_request,
    validate_grant_for_action,
)
from .authorize import AuthorizationResult, authorize
from .reversibility import (
    ActionEffectMeta,
    ReversibilityClass,
    model_attempted_self_confirm,
    resolve_action_effect,
    strip_forgery_confirmation_args,
)
from .semantic_firewall import FirewallDecision, FirewallOutcome, evaluate_semantic_firewall
from .undo_journal import register_undo_record

log = logging.getLogger("jarvis.policy.reversibility_gate")


@dataclass
class SideEffectDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    effect: ActionEffectMeta
    authorization: AuthorizationResult | None = None
    firewall: FirewallDecision | None = None
    action_id: str = ""
    pending_approval_id: str | None = None
    grant_id: str | None = None
    parked: bool = False
    self_confirm_attempt: bool = False
    effective_level: Any = None
    capability: str = ""
    audit: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "effect": self.effect.as_dict(),
            "authorization": self.authorization.as_dict() if self.authorization else None,
            "firewall": self.firewall.as_dict() if self.firewall else None,
            "action_id": self.action_id,
            "pending_approval_id": self.pending_approval_id,
            "grant_id": self.grant_id,
            "parked": self.parked,
            "self_confirm_attempt": self.self_confirm_attempt,
            "effective_level": getattr(self.effective_level, "value", self.effective_level),
            "capability": self.capability,
            "audit": self.audit,
        }


def _denial(
    *,
    effect: ActionEffectMeta,
    reason: str,
    authorization: AuthorizationResult | None = None,
    firewall: FirewallDecision | None = None,
    requires_approval: bool = False,
    self_confirm_attempt: bool = False,
    action_id: str = "",
    pending_approval_id: str | None = None,
    parked: bool = False,
) -> SideEffectDecision:
    return SideEffectDecision(
        allowed=False,
        requires_approval=requires_approval,
        reason=reason,
        effect=effect,
        authorization=authorization,
        firewall=firewall,
        action_id=action_id,
        pending_approval_id=pending_approval_id,
        parked=parked,
        self_confirm_attempt=self_confirm_attempt,
        effective_level=authorization.effective_level if authorization else None,
        capability=authorization.capability if authorization else "",
        audit={
            "original_action": effect.as_dict(),
            "authorization_allowed": bool(authorization and authorization.allowed),
            "firewall_outcome": firewall.outcome.value if firewall else None,
            "outcome": "approval_required" if requires_approval else "denied",
        },
    )


def evaluate_side_effect(
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
) -> SideEffectDecision:
    """Full RFC-0031 gate. Model confirmation args never create or satisfy a grant."""
    raw_args = arguments if isinstance(arguments, dict) else {}
    self_confirm = model_attempted_self_confirm(raw_args)
    args = strip_forgery_confirmation_args(raw_args)
    act = str(action or args.get("action") or "").strip().lower()

    effect = resolve_action_effect(tool_name, action=act, arguments=args, risk=risk)
    action_id = action_id_for(tool_name, effect.action, effect.target, task_id=task_id)

    # 1) Ordinary authorization — reversibility cannot override deny.
    auth = authorize(
        tool_name,
        action=act or None,
        arguments=args,
        risk=risk,
        profile_id=profile_id,
        approved=False,  # grants checked separately; model cannot set this
    )
    if not auth.allowed and not auth.requires_approval:
        return _denial(
            effect=effect,
            reason=auth.reason,
            authorization=auth,
            self_confirm_attempt=self_confirm,
            action_id=action_id,
        )

    # 2) Semantic firewall — may only tighten.
    firewall = evaluate_semantic_firewall(
        tool_name=tool_name,
        action=act,
        arguments=args,
        effect=effect,
        task_id=task_id,
    )
    if firewall.blocks:
        return _denial(
            effect=effect,
            reason=firewall.explanation,
            authorization=auth,
            firewall=firewall,
            self_confirm_attempt=self_confirm,
            action_id=action_id,
        )

    grant = validate_grant_for_action(
        grant_id,
        action_id=action_id,
        tool_name=tool_name,
        target=effect.target,
        arguments=raw_args,
    )
    has_grant = grant is not None

    needs_human = (
        auth.requires_approval
        or firewall.requires_approval
        or effect.reversibility in {ReversibilityClass.IRREVERSIBLE, ReversibilityClass.UNKNOWN}
        or effect.high_consequence
        or effect.destructive_effect
        or effect.credential_effect
        or effect.financial_effect
        or (effect.external_side_effect and not effect.safely_reversible)
    )

    # COMPENSATABLE auto only when compensation is well-defined and policy-safe.
    if (
        not needs_human
        and effect.reversibility == ReversibilityClass.COMPENSATABLE
        and not effect.compensatable_auto
    ):
        needs_human = True

    if effect.safely_reversible and effect.side_effecting and not needs_human:
        return SideEffectDecision(
            allowed=True,
            requires_approval=False,
            reason="policy-permitted low-risk REVERSIBLE action; durable undo will be registered after success",
            effect=effect,
            authorization=auth,
            firewall=firewall,
            action_id=action_id,
            self_confirm_attempt=self_confirm,
            effective_level=auth.effective_level,
            capability=auth.capability,
            audit={
                "original_action": effect.as_dict(),
                "approval": None,
                "outcome": "allow_reversible",
                "self_confirm_ignored": self_confirm,
            },
        )

    if effect.compensatable_auto and not needs_human:
        return SideEffectDecision(
            allowed=True,
            requires_approval=False,
            reason="policy-permitted COMPENSATABLE action with local compensation",
            effect=effect,
            authorization=auth,
            firewall=firewall,
            action_id=action_id,
            self_confirm_attempt=self_confirm,
            effective_level=auth.effective_level,
            capability=auth.capability,
            audit={
                "original_action": effect.as_dict(),
                "approval": None,
                "outcome": "allow_compensatable",
                "compensation": effect.compensation.as_dict() if effect.compensation else None,
            },
        )

    if not effect.side_effecting and not needs_human:
        return SideEffectDecision(
            allowed=True,
            requires_approval=False,
            reason="observation-only action",
            effect=effect,
            authorization=auth,
            firewall=firewall,
            action_id=action_id,
            self_confirm_attempt=self_confirm,
            effective_level=auth.effective_level,
            capability=auth.capability,
            audit={"original_action": effect.as_dict(), "outcome": "allow_readonly"},
        )

    if has_grant:
        return SideEffectDecision(
            allowed=True,
            requires_approval=False,
            reason="ApprovalGrant satisfied human gate",
            effect=effect,
            authorization=auth,
            firewall=firewall,
            action_id=action_id,
            grant_id=grant["id"],
            self_confirm_attempt=self_confirm,
            effective_level=auth.effective_level,
            capability=auth.capability,
            audit={
                "original_action": effect.as_dict(),
                "approval": {
                    "grant_id": grant["id"],
                    "origin_channel": grant.get("origin_channel"),
                    "actor": grant.get("actor"),
                    "decision": grant.get("decision"),
                    "policy_version": grant.get("policy_version"),
                },
                "outcome": "allow_with_grant",
                "self_confirm_ignored": self_confirm,
            },
        )

    # Human gate — park durable step without holding worker when requested.
    reason = (
        auth.reason
        if auth.requires_approval
        else firewall.explanation
        if firewall.requires_approval
        else f"{effect.reversibility.value} / high-consequence effect requires ApprovalGrant"
    )
    if self_confirm:
        reason = (
            f"{reason} (model confirmation parameters were ignored and cannot satisfy this gate)"
        )

    pending_id = None
    parked = False
    if park_if_needed:
        pending = park_approval_request(
            action_id=action_id,
            tool_name=tool_name,
            action=effect.action,
            scope={
                "arguments_digest": _safe_arg_digest(args),
                "reversibility": effect.reversibility.value,
            },
            target=effect.target,
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            step_key=step_key,
            reason=reason,
            effect=effect.as_dict(),
        )
        pending_id = pending["id"]
        parked = True
        try:
            from ..agent.coding_workers import add_decision_inbox_item

            add_decision_inbox_item(
                kind="rfc0031_approval",
                title=f"Approve {tool_name}.{effect.action}",
                detail=(
                    f"{reason}\n"
                    f"target={effect.target}\n"
                    f"reversibility={effect.reversibility.value}\n"
                    f"pending_id={pending_id}"
                )[:1200],
                task_id=task_id or action_id,
            )
        except Exception as exc:  # noqa: BLE001 — inbox optional in minimal tests
            log.debug("decision inbox park skipped: %s", exc)

    return _denial(
        effect=effect,
        reason=reason,
        authorization=auth,
        firewall=firewall,
        requires_approval=True,
        self_confirm_attempt=self_confirm,
        action_id=action_id,
        pending_approval_id=pending_id,
        parked=parked,
    )


def _safe_arg_digest(args: dict[str, Any]) -> str:
    import hashlib
    import json as _json

    raw = _json.dumps(args, sort_keys=True, default=str)[:4000]
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _prior_state_is_restorable(prior_state: dict[str, Any] | None, *, snapshot_required: bool) -> bool:
    if not isinstance(prior_state, dict) or not prior_state:
        return False
    kind = str(prior_state.get("kind") or "")
    if kind == "filesystem_bytes":
        # New path (existed=False) is restorable via delete; existing needs snapshot_path.
        if prior_state.get("existed") is False:
            return True
        return bool(prior_state.get("snapshot_path"))
    if kind == "settings_value":
        return "previous_value" in prior_state and bool(prior_state.get("key"))
    if snapshot_required:
        return False
    return kind not in {"", "metadata_only"}


def register_post_success_undo(
    decision: SideEffectDecision,
    *,
    prior_state: dict[str, Any] | None = None,
    post_state: dict[str, Any] | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    step_key: str | None = None,
) -> dict[str, Any] | None:
    """Create durable undo record after a successful reversible/compensatable action.

    When ``snapshot_required``, refuses to register a non-restorable prior_state
    (raises ``ValueError``) so callers cannot claim reversible success with a fake undo.
    """
    if not decision.allowed:
        return None
    effect = decision.effect
    if not effect.side_effecting:
        return None
    if effect.reversibility not in {
        ReversibilityClass.REVERSIBLE,
        ReversibilityClass.COMPENSATABLE,
    }:
        return None
    if effect.snapshot_required and not _prior_state_is_restorable(
        prior_state, snapshot_required=True
    ):
        raise ValueError(
            "snapshot_required: refusing to register undo without restorable prior_state "
            "(filesystem snapshot or settings previous_value)"
        )
    undo_op = (
        effect.compensation.operation
        if effect.compensation and effect.compensation.operation
        else f"{effect.tool_name}.undo_{effect.action}"
    )
    preconditions = (
        list(effect.compensation.preconditions)
        if effect.compensation
        else ["post_state_matches"]
    )
    return register_undo_record(
        tool_name=effect.tool_name,
        action=effect.action,
        target=effect.target,
        reversibility=effect.reversibility.value,
        undo_operation=undo_op,
        preconditions=preconditions,
        prior_state=prior_state,
        post_state=post_state,
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        step_key=step_key,
        compensation_has_external_effects=bool(
            effect.compensation and effect.compensation.has_external_effects
        ),
        summary=effect.recovery_summary or f"Undo {effect.tool_name}.{effect.action}",
    )
