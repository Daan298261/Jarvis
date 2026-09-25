"""Typed Reflex surfaces for hot-path decision classes (RFC-0171).

Browser operation/target is a typed decision helper only — full fast loop is RFC-0172.
"""

from __future__ import annotations

from typing import Any

from .reflex import decide
from .types import Answer, DecisionResult, PrivacyMode, Question


def route_persona_model(
    *,
    user_message: str,
    candidates: list[str],
    preferred_profile: str = "",
    active_persona: str = "",
    deadline_ms: float = 80.0,
    privacy: PrivacyMode = "local_only",
) -> DecisionResult:
    choices = tuple(dict.fromkeys([*(c for c in candidates if c), "default"]))
    return decide(
        {
            "user_message": user_message,
            "preferred_profile": preferred_profile,
            "active_persona": active_persona,
            "candidate_profiles": list(choices),
        },
        [
            Question(
                id="route_profile",
                type="choice",
                prompt="Which persona/model profile should handle this turn?",
                choices=choices,
            )
        ],
        "persona_model_routing",
        deadline_ms,
        privacy,
    )


def select_tools(
    *,
    user_message: str,
    candidates: list[str],
    deadline_ms: float = 80.0,
    privacy: PrivacyMode = "local_only",
) -> DecisionResult:
    tools = [name for name in candidates if name][:64]
    choices = tuple([*tools, "none"]) if tools else ("none",)
    return decide(
        {"user_message": user_message, "candidate_tools": tools},
        [
            Question(
                id="tool_select",
                type="choice",
                prompt="Which retrieved tool should this turn use? none if chat-only.",
                choices=choices,
            )
        ],
        "tool_selection",
        deadline_ms,
        privacy,
    )


def score_memory_relevance(
    *,
    user_message: str,
    candidates: list[dict[str, Any]],
    deadline_ms: float = 80.0,
    privacy: PrivacyMode = "local_only",
) -> DecisionResult:
    """
    Score each evidence/memory candidate. Same-state questions are batched into
    one Reflex call.
    """
    questions: list[Question] = []
    excerpts: dict[str, str] = {}
    for idx, row in enumerate(candidates[:32]):
        qid = f"memory_{idx}"
        excerpt = str(row.get("excerpt") or row.get("text") or row.get("title") or "")
        excerpts[qid] = excerpt
        questions.append(
            Question(
                id=qid,
                type="score",
                prompt=f"How relevant is this evidence to the user message? {excerpt[:160]}",
                min_score=0.0,
                max_score=1.0,
            )
        )
    if not questions:
        return decide(
            {"user_message": user_message},
            [Question(id="memory_none", type="score", prompt="No candidates", min_score=0.0, max_score=1.0)],
            "memory_relevance",
            deadline_ms,
            privacy,
        )
    return decide(
        {"user_message": user_message, "excerpts": excerpts},
        questions,
        "memory_relevance",
        deadline_ms,
        privacy,
    )


def browser_operation_target(
    *,
    goal: str,
    operations: list[str],
    target_ids: list[str],
    suggested_operation: str = "",
    suggested_target_id: str = "",
    frame_id: str = "",
    deadline_ms: float = 80.0,
    privacy: PrivacyMode = "local_only",
) -> DecisionResult:
    """
    One batched Reflex call for operation + target_id (+ optional done/block).
    Executor must resolve target_id against the current ActionFrame (RFC-0172).
    """
    ops = tuple(dict.fromkeys([*(o for o in operations if o), "NOOP"]))
    targets = tuple(dict.fromkeys([*(t for t in target_ids if t), "none"]))
    return decide(
        {
            "user_message": goal,
            "suggested_operation": suggested_operation,
            "suggested_target_id": suggested_target_id,
            "frame_id": frame_id,
        },
        [
            Question(
                id="operation",
                type="choice",
                prompt="Which browser/computer operation should run next?",
                choices=ops,
            ),
            Question(
                id="target_id",
                type="choice",
                prompt="Which actionable target id from the current frame?",
                choices=targets,
            ),
            Question(
                id="done",
                type="boolean",
                prompt="Is the goal already satisfied?",
            ),
            Question(
                id="block",
                type="boolean",
                prompt="Should the loop stop because the action is unsafe or impossible?",
            ),
        ],
        "browser_operation_target",
        deadline_ms,
        privacy,
    )


def complexity_and_escalate(
    *,
    user_message: str,
    local_complexity: int = 1,
    local_escalate: bool = False,
    deadline_ms: float = 80.0,
    privacy: PrivacyMode = "local_only",
) -> DecisionResult:
    return decide(
        {
            "user_message": user_message,
            "local_complexity": local_complexity,
            "local_escalate": local_escalate,
        },
        [
            Question(
                id="complexity_tier",
                type="score",
                prompt="Task complexity 1-4 matching Jarvis answer tiers.",
                min_score=1.0,
                max_score=4.0,
            ),
            Question(
                id="escalate",
                type="boolean",
                prompt="Does this need a stronger model than the current orchestrator should answer?",
            ),
        ],
        "complexity_escalation",
        deadline_ms,
        privacy,
    )


def answer_value(result: DecisionResult, question_id: str, default: Any = None) -> Any:
    answer: Answer | None = result.answers.get(question_id)
    if answer is None:
        return default
    return answer.value


def privacy_for_tier(decision_tier: str) -> PrivacyMode:
    if decision_tier in {"jev_optional", "jev_plus"}:
        return "allow_cloud"
    return "local_only"
