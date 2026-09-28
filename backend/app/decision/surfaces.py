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


NO_TOOL_DESCRIPTION = "no tool: greeting, small talk, opinion or a question answered from knowledge"


def _tool_description(name: str) -> str:
    try:
        from ..tools.registry import REGISTRY

        tool = REGISTRY.tools.get(name)
    except Exception:  # noqa: BLE001 — descriptions are an accuracy aid, never required
        tool = None
    text = str(getattr(tool, "description", "") or "").strip()
    return f"{name}: {text.split('. ')[0][:160]}" if text else name


def select_tools(
    *,
    user_message: str,
    candidates: list[str],
    deadline_ms: float = 80.0,
    privacy: PrivacyMode = "local_only",
    descriptions: dict[str, str] | None = None,
) -> DecisionResult:
    tools = [name for name in candidates if name][:64]
    choices = tuple([*tools, "none"]) if tools else ("none",)
    described = descriptions or {}
    # Candidates live in the question; repeating them in the state biases encoders toward them.
    return decide(
        {"user_message": user_message},
        [
            Question(
                id="tool_select",
                type="choice",
                prompt="Which tool does this request need?",
                choices=choices,
                descriptions=tuple(
                    NO_TOOL_DESCRIPTION if name == "none" else described.get(name) or _tool_description(name)
                    for name in choices
                ),
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
    frame_nodes: list[dict[str, Any]] | None = None,
    deadline_ms: float = 80.0,
    privacy: PrivacyMode = "local_only",
) -> DecisionResult:
    """
    One batched Reflex call for operation + target_id (+ optional done/block).
    Executor must resolve target_id against the current ActionFrame (RFC-0172).

    ``frame_nodes`` is the semantic snapshot (target_id, role, name, value, ops);
    without it a provider would be choosing among opaque ids like ``t3``.
    """
    ops = tuple(dict.fromkeys(o for o in operations if o)) or ("DONE",)
    targets = tuple(dict.fromkeys([*(t for t in target_ids if t), "none"]))
    labels = {
        str(node.get("target_id")): " ".join(
            part for part in (str(node.get("role") or ""), repr(str(node.get("name") or ""))) if part
        )
        for node in (frame_nodes or [])
        if isinstance(node, dict) and node.get("target_id")
    }
    target_descriptions = tuple(
        labels.get(t, "no target (for DONE/BLOCK)" if t == "none" else t) for t in targets
    )
    return decide(
        {
            "user_message": goal,
            "suggested_operation": suggested_operation,
            "suggested_target_id": suggested_target_id,
            "frame_id": frame_id,
            "nodes": [
                f"{node.get('target_id')}: {node.get('role')} {str(node.get('name') or '')!r}"
                f" value={str(node.get('value') or '')[:60]!r} ops={','.join(node.get('ops') or [])}"
                for node in (frame_nodes or [])
                if isinstance(node, dict)
            ],
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
                prompt="Which actionable target from the current frame?",
                choices=targets,
                descriptions=target_descriptions,
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
