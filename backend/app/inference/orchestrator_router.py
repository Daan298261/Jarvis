"""RFC-0115 Ornith routing envelope, structured actions, and rule/model merge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from ..providers.base import ChatMessage
from .complexity_scorer import ComplexityResult, score_question_complexity
from .profile_roles import infer_runtime_role_and_tier
from .runtime_profiles import RuntimeProfile, list_runtime_profiles

RouterAction = Literal["answer_basic", "use_tool", "switch_model", "delegate", "ask_clarification"]

ROUTER_ACTIONS = ("answer_basic", "use_tool", "switch_model", "delegate", "ask_clarification")


@dataclass
class RouterDecision:
    action: RouterAction
    required_answer_tier: int
    minimum_answer_tier: int
    reason: str
    hard_rule: bool = False
    prefer_tool: bool = False
    task_class: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    preferred_context: int = 32768

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "required_answer_tier": self.required_answer_tier,
            "minimum_answer_tier": self.minimum_answer_tier,
            "reason": self.reason,
            "hard_rule": self.hard_rule,
            "prefer_tool": self.prefer_tool,
            "task_class": self.task_class,
            "required_capabilities": list(self.required_capabilities),
            "preferred_context": self.preferred_context,
        }


def build_routing_envelope(
    *,
    latest_user_message: str,
    conversation_summary: str,
    recent_turn_count: int,
    current_model: str,
    tools_available: bool,
    vision_requested: bool,
    profiles: list[RuntimeProfile] | None = None,
) -> dict[str, Any]:
    catalog = profiles if profiles is not None else list_runtime_profiles()
    available = []
    for row in catalog:
        if not row.enabled:
            continue
        role, tier = infer_runtime_role_and_tier(row.model_profile or row.name)
        if row.runtime_role:
            role = row.runtime_role
        if row.answer_tier:
            tier = int(row.answer_tier)
        available.append(
            {
                "id": row.name,
                "role": role,
                "answer_tier": tier,
                "context": int(row.context_limit or 16384),
            }
        )
    return {
        "latest_user_message": latest_user_message,
        "conversation_summary": conversation_summary,
        "recent_turn_count": recent_turn_count,
        "current_model": current_model,
        "available_models": available,
        "tools_available": tools_available,
        "vision_requested": vision_requested,
    }


def _action_from_baseline(baseline: ComplexityResult, current_tier: int) -> RouterAction:
    if baseline.prefer_tool and baseline.minimum_answer_tier >= 2:
        return "use_tool"
    if baseline.minimum_answer_tier >= 2 and current_tier < baseline.minimum_answer_tier:
        return "switch_model"
    if baseline.tier <= 1 and current_tier <= 1:
        return "answer_basic"
    if baseline.minimum_answer_tier >= 2:
        return "switch_model"
    return "answer_basic"


def merge_router_output(
    baseline: ComplexityResult,
    *,
    current_model: str,
    model_output: dict[str, Any] | None = None,
) -> RouterDecision:
    """Rules first; optional model JSON may raise tier, almost never lower a hard rule."""
    _, current_tier = infer_runtime_role_and_tier(current_model)
    required = baseline.minimum_answer_tier
    action = _action_from_baseline(baseline, current_tier)
    reason = "; ".join(baseline.signals) or "complexity baseline"
    task_class = baseline.task_class_hint
    caps: list[str] = []

    if model_output:
        raw_action = str(model_output.get("action") or "").strip().lower()
        if raw_action in ROUTER_ACTIONS:
            action = raw_action  # type: ignore[assignment]
        model_tier = model_output.get("required_answer_tier")
        if model_tier is not None:
            try:
                raised = int(model_tier)
                required = max(required, raised)
            except (TypeError, ValueError):
                pass
        if not baseline.hard_rule and model_output.get("required_answer_tier") is not None:
            try:
                required = max(required, int(model_output["required_answer_tier"]))
            except (TypeError, ValueError):
                pass
        if baseline.hard_rule:
            required = max(required, baseline.minimum_answer_tier)
        if model_output.get("reason"):
            reason = str(model_output["reason"])
        if model_output.get("task_class"):
            task_class = str(model_output["task_class"])
        raw_caps = model_output.get("required_capabilities") or []
        if isinstance(raw_caps, list):
            caps = [str(c) for c in raw_caps]

    if baseline.hard_rule and baseline.minimum_answer_tier >= 2 and action == "answer_basic":
        action = "use_tool" if baseline.prefer_tool else "switch_model"

    return RouterDecision(
        action=action,
        required_answer_tier=max(baseline.tier, required),
        minimum_answer_tier=required,
        reason=reason,
        hard_rule=baseline.hard_rule,
        prefer_tool=baseline.prefer_tool,
        task_class=task_class,
        required_capabilities=caps,
    )


def resolve_router_decision(
    user_message: str,
    *,
    current_model: str,
    task_class: str = "",
    recent_turn_count: int = 0,
    vision_requested: bool = False,
    prior_failures: int = 0,
    model_output: dict[str, Any] | None = None,
) -> RouterDecision:
    baseline = score_question_complexity(
        user_message,
        task_class=task_class,
        recent_turn_count=recent_turn_count,
        vision_requested=vision_requested,
        prior_failures=prior_failures,
    )
    return merge_router_output(baseline, current_model=current_model, model_output=model_output)


def parse_router_model_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
