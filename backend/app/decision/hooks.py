"""Wire Reflex / Jev into speak-class, tool retrieval, complexity, and approval (RFC-0116/0171)."""

from __future__ import annotations

from typing import Any

from ..policy.authorize import AuthorizationResult, authorize
from ..tts.reply_class import ReplySpeechClass, register_reply_classifier_hook
from .policy import apply_complexity_tier, approval_popup_required, local_complexity_tier, should_escalate
from .surfaces import answer_value, complexity_and_escalate, privacy_for_tier
from .tier import decide_turn, resolve_status


def _speak_hook(text: str, user_prompt: str | None) -> ReplySpeechClass | None:
    status = resolve_status()
    privacy = privacy_for_tier(str(status.get("decision_tier") or "local"))
    from .reflex import decide
    from .types import Question

    result = decide(
        {"user_message": user_prompt or text},
        [
            Question(
                id="speak_class",
                type="choice",
                prompt="Is the upcoming assistant reply social small-talk or technical?",
                choices=("social", "technical"),
            )
        ],
        "speak_class",
        80.0,
        privacy,
    )
    speak = answer_value(result, "speak_class")
    if speak in {"social", "technical"}:
        return speak  # type: ignore[return-value]
    return None


def register_decision_hooks() -> None:
    register_reply_classifier_hook(_speak_hook)


def classify_complexity(prompt: str) -> int:
    local = local_complexity_tier(prompt)
    status = resolve_status()
    result = complexity_and_escalate(
        user_message=prompt,
        local_complexity=local,
        privacy=privacy_for_tier(str(status.get("decision_tier") or "local")),
    )
    raw = answer_value(result, "complexity_tier")
    try:
        scored = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        scored = None
    return apply_complexity_tier(local, scored)


def classify_escalate(prompt: str, *, local_escalate: bool = False) -> bool:
    status = resolve_status()
    result = complexity_and_escalate(
        user_message=prompt,
        local_complexity=local_complexity_tier(prompt),
        local_escalate=local_escalate,
        privacy=privacy_for_tier(str(status.get("decision_tier") or "local")),
    )
    escalate = answer_value(result, "escalate")
    if isinstance(escalate, bool):
        return should_escalate(local_escalate, 1.0 if escalate else 0.0)
    try:
        return should_escalate(local_escalate, float(escalate) if escalate is not None else None)
    except (TypeError, ValueError):
        return local_escalate


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
