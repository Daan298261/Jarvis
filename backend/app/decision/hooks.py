"""Wire Jev into speak-class, tool retrieval, complexity, and approval (RFC-0116)."""

from __future__ import annotations

from typing import Any

from ..policy.authorize import AuthorizationResult, authorize
from ..tts.reply_class import ReplySpeechClass, register_reply_classifier_hook
from .policy import apply_complexity_tier, approval_popup_required, local_complexity_tier, should_escalate
from .tier import decide_turn, jev_calls_allowed, resolve_status


def _speak_hook(text: str, user_prompt: str | None) -> ReplySpeechClass | None:
    allowed, _reason = jev_calls_allowed(resolve_status())
    if not allowed:
        return None
    decision = decide_turn(
        user_message=user_prompt or text,
        candidate_tools=[],
        local_speak=None,
        local_complexity=local_complexity_tier(user_prompt or text),
    )
    if decision.get("source") != "jev":
        return None
    speak = decision.get("speak_class")
    if speak in {"social", "technical"}:
        return speak  # type: ignore[return-value]
    return None


def register_decision_hooks() -> None:
    register_reply_classifier_hook(_speak_hook)


def classify_complexity(prompt: str) -> int:
    local = local_complexity_tier(prompt)
    allowed, _reason = jev_calls_allowed(resolve_status())
    if not allowed:
        return local
    decision = decide_turn(
        user_message=prompt,
        candidate_tools=[],
        local_complexity=local,
    )
    if decision.get("source") != "jev":
        return local
    return apply_complexity_tier(local, float(decision.get("complexity_tier") or local))


def classify_escalate(prompt: str, *, local_escalate: bool = False) -> bool:
    allowed, _reason = jev_calls_allowed(resolve_status())
    if not allowed:
        return local_escalate
    decision = decide_turn(
        user_message=prompt,
        candidate_tools=[],
        local_complexity=local_complexity_tier(prompt),
        local_escalate=local_escalate,
    )
    if decision.get("source") != "jev":
        return local_escalate
    return should_escalate(local_escalate, 1.0 if decision.get("escalate") else 0.0)


def authorize_with_jev(
    tool_name: str,
    *,
    action: str | None = None,
    arguments: dict | None = None,
    **kwargs: Any,
) -> AuthorizationResult:
    result = authorize(tool_name, action=action, arguments=arguments, **kwargs)
    if not result.allowed and not result.requires_approval:
        return result
    allowed, _reason = jev_calls_allowed(resolve_status())
    if not allowed:
        return result
    decision = decide_turn(
        user_message=str((arguments or {}).get("prompt") or action or tool_name),
        candidate_tools=[tool_name],
        policy_requires_approval=result.requires_approval,
        policy_deny=not result.allowed and not result.requires_approval,
    )
    needed = approval_popup_required(
        policy_requires=result.requires_approval,
        policy_deny=not result.allowed and not result.requires_approval,
        jev_noul=1.0 if decision.get("approval_needed") else 0.0,
    )
    if result.requires_approval:
        return result
    if needed and result.allowed:
        return AuthorizationResult(
            allowed=False,
            requires_approval=True,
            reason="Decision accelerator asked for confirmation before this step.",
            effective_level=result.effective_level,
            capability=result.capability,
        )
    return result
