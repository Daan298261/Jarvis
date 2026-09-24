"""Typed Reflex call-site helpers (RFC-0171). Does not rewrite browser runtime."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .policy import apply_complexity_tier, approval_popup_required, local_complexity_tier, should_escalate
from .reflex import decide
from .types import Answer, DecisionResult, PrivacyMode, Question


def _privacy_for_cloud_opt_in(cloud_ok: bool) -> PrivacyMode:
    return "cloud_ok" if cloud_ok else "local_only"


def decide_tool_selection(
    prompt: str,
    candidates: Sequence[str],
    *,
    deadline_ms: int = 80,
    cloud_ok: bool = False,
) -> DecisionResult:
    tools = [name for name in candidates if name][:32]
    choices = tuple([*tools, "none"]) if tools else ("none",)
    return decide(
        {
            "user_message": (prompt or "")[:800],
            "candidate_tools": tools,
            "shortlist": tools,
        },
        [
            Question(
                id="tool_select",
                type="choice",
                prompt="Which retrieved tool should this turn use? none if chat-only.",
                choices=choices,
            )
        ],
        "tool_selection",
        deadline_ms=deadline_ms,
        privacy=_privacy_for_cloud_opt_in(cloud_ok),
    )


def decide_tool_shortlist(
    prompt: str,
    candidates: Sequence[str],
    *,
    limit: int = 6,
    deadline_ms: int = 80,
    cloud_ok: bool = False,
) -> list[str]:
    local = [name for name in candidates if name]
    if not local:
        return []
    # High-cardinality: shortlist with rules/Laya over a compact choice of keep/drop is expensive;
    # use one selection then pin selected first.
    result = decide_tool_selection(prompt, local, deadline_ms=deadline_ms, cloud_ok=cloud_ok)
    selected = result.value("tool_select")
    if selected and selected != "none" and selected in local:
        return [selected, *[name for name in local if name != selected]][: max(1, limit)]
    return local[: max(1, limit)]


def decide_persona_model_route(
    prompt: str,
    profile_choices: Sequence[str],
    *,
    preferred_profile: str = "",
    local_complexity: int | None = None,
    deadline_ms: int = 80,
    cloud_ok: bool = False,
) -> DecisionResult:
    choices = tuple(name for name in profile_choices if name)
    if not choices:
        raise ValueError("profile_choices required")
    complexity = local_complexity if local_complexity is not None else local_complexity_tier(prompt)
    return decide(
        {
            "user_message": (prompt or "")[:800],
            "preferred_profile": preferred_profile,
            "local_profile": preferred_profile,
            "local_complexity": complexity,
        },
        [
            Question(
                id="model_profile",
                type="choice",
                prompt="Which runtime model profile should handle this turn?",
                choices=choices,
            ),
            Question(
                id="complexity_tier",
                type="score",
                prompt="Task complexity 1-4 matching Jarvis answer tiers.",
                score_min=1.0,
                score_max=4.0,
            ),
            Question(
                id="escalate",
                type="boolean",
                prompt="Does this need a stronger model than the current orchestrator should answer?",
            ),
        ],
        "persona_model_routing",
        deadline_ms=deadline_ms,
        privacy=_privacy_for_cloud_opt_in(cloud_ok),
    )


def decide_memory_relevance(
    query: str,
    candidates: Sequence[dict[str, Any]],
    *,
    deadline_ms: int = 80,
    cloud_ok: bool = False,
) -> list[dict[str, Any]]:
    """Score each memory/evidence candidate; returns candidates sorted by Reflex score."""
    if not candidates:
        return []
    # Batch same-state questions: one decide() with many score questions sharing query state.
    questions: list[Question] = []
    compact: list[dict[str, Any]] = []
    for index, row in enumerate(candidates[:12]):
        excerpt = str(row.get("excerpt") or row.get("text") or row.get("content") or "")[:400]
        compact.append({**row, "_reflex_id": f"c{index}", "excerpt": excerpt})
        questions.append(
            Question(
                id=f"rel_{index}",
                type="score",
                prompt=f"Relevance of candidate {index} to the query.",
                score_min=0.0,
                score_max=1.0,
            )
        )
    state = {
        "query": (query or "")[:500],
        "user_message": (query or "")[:500],
        "candidates": [{"id": c["_reflex_id"], "excerpt": c["excerpt"]} for c in compact],
    }
    # Put first excerpt also at top-level for rules adapter lexical overlap.
    if compact:
        state["excerpt"] = " \n".join(c["excerpt"] for c in compact)
    result = decide(
        state,
        questions,
        "memory_relevance",
        deadline_ms=deadline_ms,
        privacy=_privacy_for_cloud_opt_in(cloud_ok),
    )
    scored: list[tuple[float, dict[str, Any]]] = []
    for index, row in enumerate(compact):
        score = float(result.value(f"rel_{index}", 0.0) or 0.0)
        scored.append((score, {k: v for k, v in row.items() if k != "_reflex_id"} | {"reflex_score": score}))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("rel_path") or item[1].get("id") or "")))
    return [row for _score, row in scored]


def decide_browser_operation_target(
    *,
    frame_id: str,
    actionable: Sequence[dict[str, Any]],
    suggested_operation: str = "",
    suggested_target_id: str = "",
    deadline_ms: int = 60,
    cloud_ok: bool = False,
) -> DecisionResult:
    """Typed op+target decision for RFC-0172 consumers. Does not execute browser actions."""
    operations = (
        "click",
        "type_text",
        "scroll",
        "hover",
        "key",
        "noop",
        "done",
        "block",
    )
    target_ids = tuple(
        str(node.get("target_id") or node.get("id") or "")
        for node in actionable
        if str(node.get("target_id") or node.get("id") or "")
    )[:64]
    if not target_ids:
        target_ids = ("none",)
    state = {
        "frame_id": frame_id,
        "suggested_operation": suggested_operation,
        "suggested_target_id": suggested_target_id,
        "nodes": [
            {
                "target_id": str(node.get("target_id") or node.get("id") or ""),
                "role": node.get("role"),
                "name": str(node.get("name") or "")[:80],
            }
            for node in list(actionable)[:64]
        ],
        "user_message": f"frame={frame_id} op={suggested_operation} target={suggested_target_id}",
    }
    return decide(
        state,
        [
            Question(
                id="operation",
                type="choice",
                prompt="Which operation should run on the current actionable frame?",
                choices=operations,
            ),
            Question(
                id="target_id",
                type="choice",
                prompt="Which target_id from the current frame should receive the operation?",
                choices=target_ids,
            ),
            Question(
                id="done",
                type="boolean",
                prompt="Is the browser/computer task already complete?",
            ),
            Question(
                id="block",
                type="boolean",
                prompt="Should the loop stop because the frame is unsafe or stale?",
            ),
        ],
        "browser_operation_target",
        deadline_ms=deadline_ms,
        privacy=_privacy_for_cloud_opt_in(cloud_ok),
    )


def compose_turn_decisions(
    *,
    user_message: str,
    candidate_tools: Sequence[str],
    local_speak: str | None = None,
    local_complexity: int = 1,
    local_escalate: bool = False,
    policy_requires_approval: bool = False,
    policy_deny: bool = False,
    cloud_ok: bool = False,
    deadline_ms: int = 100,
) -> dict[str, Any]:
    """Batch same-state control-path questions into one Reflex call (replaces decide_turn shape)."""
    tools = [name for name in candidate_tools if name][:32]
    questions: list[Question] = [
        Question(
            id="speak_class",
            type="choice",
            prompt="Is the upcoming assistant reply social small-talk or technical?",
            choices=("social", "technical"),
        ),
        Question(
            id="complexity_tier",
            type="score",
            prompt="Task complexity 1-4 matching Jarvis answer tiers.",
            score_min=1.0,
            score_max=4.0,
        ),
        Question(
            id="escalate",
            type="boolean",
            prompt="Does this need a stronger model than the current orchestrator should answer?",
        ),
        Question(
            id="approval_needed",
            type="boolean",
            prompt="Does this step need Always allow / Allow this time / Deny before it runs?",
        ),
    ]
    if tools:
        questions.append(
            Question(
                id="tool_select",
                type="choice",
                prompt="Which retrieved tool should this turn use? none if chat-only.",
                choices=tuple([*tools, "none"]),
            )
        )
    result = decide(
        {
            "user_message": (user_message or "")[:800],
            "candidate_tools": tools,
            "shortlist": tools,
            "local_complexity": local_complexity,
            "local_escalate": local_escalate,
            "policy_requires_approval": policy_requires_approval,
            "policy_deny": policy_deny,
            "local_speak": local_speak,
        },
        questions,
        "complexity_escalation",
        deadline_ms=deadline_ms,
        privacy=_privacy_for_cloud_opt_in(cloud_ok),
    )
    speak = result.value("speak_class")
    complexity_raw = result.value("complexity_tier")
    escalate_raw = result.value("escalate")
    approval_raw = result.value("approval_needed")
    tool = result.value("tool_select")

    complexity_value = apply_complexity_tier(
        local_complexity,
        float(complexity_raw) if complexity_raw is not None else None,
    )
    escalate_value = should_escalate(
        local_escalate,
        float(escalate_raw) if escalate_raw is not None else None,
        confidence=_confidence(result, "escalate"),
    )
    approval_value = approval_popup_required(
        policy_requires=policy_requires_approval,
        policy_deny=policy_deny,
        jev_noul=float(approval_raw) if approval_raw is not None else None,
        confidence=_confidence(result, "approval_needed"),
    )
    tool_value = tool if tool and tool != "none" and tool in tools else None
    speak_value = speak if speak in {"social", "technical"} else local_speak

    return {
        "source": result.source,
        "provider": result.provider,
        "provider_version": result.provider_version,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "deadline_hit": result.deadline_hit,
        "latency_ms": result.latency.total_ms,
        "model": result.provider_version,
        "answers": {qid: ans.to_dict() for qid, ans in result.answers.items()},
        "tool_select": tool_value,
        "speak_class": speak_value,
        "complexity_tier": complexity_value,
        "escalate": escalate_value,
        "approval_needed": approval_value,
        "batch_size": result.batch_size,
        "decision_class": result.decision_class,
    }


def _confidence(result: DecisionResult, question_id: str) -> float | None:
    answer: Answer | None = result.answers.get(question_id)
    return None if answer is None else answer.confidence


def cloud_opt_in_active() -> bool:
    from .tier import jev_calls_allowed, resolve_status

    allowed, _reason = jev_calls_allowed(resolve_status())
    return allowed
