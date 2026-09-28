"""Action gate: hard rules, then always-on Laya harm veto (cancel only)."""

from __future__ import annotations

import logging
from typing import Any

from ..decision.reflex import decide
from ..security.red_scenarios import HARM as HARM_QUESTION
from ..tools.base import RiskLevel
from ..tools.safety import is_destructive_operation
from .authorize import AuthorizationResult, authorize

log = logging.getLogger("jarvis.policy.action_gate")


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


def gate_tool_call(
    tool_name: str,
    *,
    action: str | None = None,
    arguments: dict[str, Any] | None = None,
    risk: RiskLevel = RiskLevel.MEDIUM,
    profile_id: str | None = None,
    approved: bool = False,
) -> AuthorizationResult:
    """Hard authorization first; Laya may only cancel. Destructive calls fail closed."""
    hard = authorize(
        tool_name,
        action=action,
        arguments=arguments,
        risk=risk,
        profile_id=profile_id,
        approved=approved,
    )
    if not hard.allowed or hard.requires_approval:
        return hard
    if approved:
        return hard

    args = arguments or {}
    command = str(args.get("command") or "") if isinstance(args, dict) else ""
    destructive = risk == RiskLevel.IRREVERSIBLE or is_destructive_operation(tool_name, args, command)
    state = {
        "user_message": f"{tool_name} {action or ''} {command or args}".strip()[:800],
        "tool_name": tool_name,
        "action": action or "",
        "destructive": destructive,
    }
    try:
        decision = decide(state, [HARM_QUESTION], "harm_veto", 80.0, "local_only")
        answer = decision.answers.get("cancel")
        cancel = _as_cancel(answer.value) if answer is not None else None
        quality = answer.confidence if answer is not None and answer.confidence is not None else 0.0
        source = decision.provider
        unsure = cancel is None or quality < 0.35 or decision.fallback_used
    except Exception as exc:  # noqa: BLE001 — fail closed only when destructive
        log.info("harm veto unavailable: %s", exc)
        cancel = None
        unsure = True
        source = "unavailable"

    if cancel is True:
        return _veto(hard, f"Laya cancelled this {tool_name} step.")
    if destructive:
        # Laya was confidently wrong on format/rm/system32 in live measure.
        # Destructive never proceeds without an explicit owner approval.
        return _veto(
            hard,
            "Destructive action blocked until you approve it.",
        )
    if unsure:
        log.debug("action gate allowed %s with unsure harm check via %s", tool_name, source)
    else:
        log.debug("action gate allowed %s via %s", tool_name, source)
    return hard


def _veto(hard: AuthorizationResult, reason: str) -> AuthorizationResult:
    return AuthorizationResult(
        allowed=False,
        requires_approval=False,
        reason=reason,
        effective_level=hard.effective_level,
        capability=hard.capability,
    )
