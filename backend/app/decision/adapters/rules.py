"""Deterministic rules adapter — always first for invariants / hard safety (RFC-0171)."""

from __future__ import annotations

import re
import time
from typing import Any

from ..policy import local_complexity_tier
from ..types import Answer, DecisionResult, LatencyBreakdown, Question

VERSION = "rules-1.0"

_SOCIAL = re.compile(r"(?i)\b(hello|hi\b|hey\b|thanks|thank you|good (morning|evening)|joke)\b")
_TECH = re.compile(r"(?i)\b(traceback|exception|pytest|refactor|api|bug|error|stack|code|file)\b")
# Hard-safety only. Laya decides first on everything else; these never wait for the model.
_OBVIOUS_HARM = re.compile(
    r"(?i)("
    r"format\s+[a-z]:"
    r"|rm\s+-rf\s+[/\\~]"
    r"|del(?:ete)?\s+\S.*(?:system32|windows\\system)"
    r"|wipe\b.*\b(?:disk|drive|volume|backup)"
    r"|diskpart\b"
    r"|cipher\s+/w"
    r")"
)


def available(*, privacy: str = "local_only", decision_class: str = "") -> tuple[bool, str]:
    return True, ""


def _answer_choice(qid: str, value: str, confidence: float = 0.85) -> Answer:
    return Answer(question_id=qid, type="choice", value=value, confidence=confidence)


def _answer_score(qid: str, value: float, confidence: float = 0.8) -> Answer:
    return Answer(question_id=qid, type="score", value=float(value), confidence=confidence)


def _answer_bool(qid: str, value: bool, confidence: float = 0.8) -> Answer:
    return Answer(question_id=qid, type="boolean", value=bool(value), confidence=confidence)


def _answer_noul(qid: str, value: float, confidence: float = 0.8) -> Answer:
    return Answer(question_id=qid, type="noul", value=float(value), confidence=confidence)


def _pick_tool(prompt: str, choices: tuple[str, ...]) -> str:
    text = (prompt or "").lower()
    for name in choices:
        if name == "none":
            continue
        if name.lower() in text:
            return name
    # Keyword heuristics for common tools
    mapping = (
        ("filesystem", ("file", "read", "write", "folder", "path")),
        ("git", ("git", "commit", "branch", "pr ", "pull request")),
        ("browser", ("browser", "webpage", "url", "http", "navigate")),
        ("terminal", ("shell", "command", "terminal", "bash")),
        ("python", ("python", "pytest", "script")),
    )
    for tool, keys in mapping:
        if tool in choices and any(k in text for k in keys):
            return tool
    return choices[0] if choices else "none"


def _score_memory(prompt: str, excerpt: str) -> float:
    tokens = set(re.findall(r"[a-z0-9_]{3,}", (prompt or "").lower()))
    hay = set(re.findall(r"[a-z0-9_]{3,}", (excerpt or "").lower()))
    if not tokens or not hay:
        return 0.15
    overlap = len(tokens & hay) / max(1, len(tokens))
    return max(0.0, min(1.0, overlap))


def decide(
    *,
    state: dict[str, Any],
    questions: list[Question],
    decision_class: str,
    deadline_ms: float = 50.0,
) -> DecisionResult:
    started = time.perf_counter()
    prompt = str(state.get("user_message") or state.get("prompt") or "")
    answers: dict[str, Answer] = {}
    hard_rule = False

    policy_deny = bool(state.get("policy_deny"))
    policy_requires = bool(state.get("policy_requires_approval"))

    for question in questions:
        qid = question.id
        if question.type == "choice":
            if qid == "request_route":
                baseline = str(state.get("baseline_route") or "managed_task")
                from ...agent.planning import (
                    MANAGED_TASK,
                    is_weather_query,
                    lta_protected_folder_path,
                    requests_agent_tools,
                    simple_app_control,
                    simple_file_control,
                )

                prompt_text = prompt
                if requests_agent_tools(prompt_text) or simple_app_control(prompt_text) or simple_file_control(prompt_text) or lta_protected_folder_path(prompt_text):
                    pick = MANAGED_TASK if MANAGED_TASK in question.choices else baseline
                elif is_weather_query(prompt_text) and "direct_lookup" in question.choices:
                    pick = "direct_lookup"
                else:
                    pick = baseline if baseline in question.choices else question.choices[-1]
                answers[qid] = _answer_choice(qid, pick, 0.9)
            elif qid == "reply_shape" or (decision_class == "request_routing" and qid == "reply_shape"):
                from ..owner_turn import infer_rules_reply_shape

                pick = infer_rules_reply_shape(
                    prompt,
                    baseline_route=str(state.get("baseline_route") or ""),
                    literal_candidate=str(state.get("literal_candidate") or ""),
                )
                if pick not in question.choices:
                    pick = question.choices[0]
                answers[qid] = _answer_choice(qid, pick, 0.9)
            elif qid == "disposition" or decision_class == "arbitration":
                from ...agent.front_responder import infer_arbitration_disposition

                pick = infer_arbitration_disposition(
                    str(state.get("front_text") or ""),
                    str(state.get("worker_text") or ""),
                    front_action=str(state.get("front_action") or ""),
                    reply_shape=str(state.get("reply_shape") or ""),
                )
                if pick not in question.choices:
                    pick = question.choices[0] if question.choices else "keep_front"
                answers[qid] = _answer_choice(qid, pick, 0.9)
            elif qid in {"tool_select", "tool_shortlist"} or decision_class in {
                "tool_selection",
                "tool_shortlist",
            }:
                pick = _pick_tool(prompt, question.choices)
                answers[qid] = _answer_choice(qid, pick, 0.7)
            elif qid in {"speak_class"} or decision_class == "speak_class":
                if _TECH.search(prompt):
                    answers[qid] = _answer_choice(qid, "technical", 0.9)
                    hard_rule = True
                elif _SOCIAL.search(prompt):
                    answers[qid] = _answer_choice(qid, "social", 0.75)
                else:
                    preferred = "technical" if "technical" in question.choices else question.choices[0]
                    answers[qid] = _answer_choice(qid, preferred, 0.55)
            elif qid in {"persona", "model_profile", "route_profile"} or (
                decision_class == "persona_model_routing" and qid.startswith("route")
            ):
                # Prefer explicit state hint, else first non-empty choice.
                hinted = str(state.get("preferred_profile") or state.get("active_persona") or "")
                persona = str(state.get("active_persona") or "").strip().lower()
                if persona == "umi" and "umi-opus-9b" in question.choices:
                    answers[qid] = _answer_choice(qid, "umi-opus-9b", 0.92)
                    hard_rule = True
                elif hinted and hinted in question.choices:
                    answers[qid] = _answer_choice(qid, hinted, 0.9)
                    hard_rule = True
                else:
                    answers[qid] = _answer_choice(qid, question.choices[0], 0.55)
            elif qid in {"operation", "browser_operation"}:
                op = str(state.get("suggested_operation") or "")
                if op and op in question.choices:
                    answers[qid] = _answer_choice(qid, op, 0.8)
                elif "CLICK" in question.choices:
                    answers[qid] = _answer_choice(qid, "CLICK", 0.5)
                else:
                    answers[qid] = _answer_choice(qid, question.choices[0], 0.5)
            elif qid in {"target_id", "browser_target"}:
                target = str(state.get("suggested_target_id") or "")
                if target and target in question.choices:
                    answers[qid] = _answer_choice(qid, target, 0.85)
                    hard_rule = hard_rule or bool(state.get("target_locked"))
                else:
                    answers[qid] = _answer_choice(qid, question.choices[0], 0.45)
            elif qid == "cancel" or decision_class == "harm_veto":
                obvious = bool(_OBVIOUS_HARM.search(prompt))
                pick = "cancel" if obvious else "allow"
                if pick not in question.choices:
                    pick = question.choices[0]
                answers[qid] = _answer_choice(qid, pick, 1.0 if obvious else 0.4)
                hard_rule = obvious
            else:
                answers[qid] = _answer_choice(qid, question.choices[0], 0.4)
        elif question.type == "score":
            if qid in {"complexity_tier"} or decision_class == "complexity_escalation":
                tier = float(local_complexity_tier(prompt))
                # Normalize 1-4 into question range when needed.
                if question.max_score <= 1.0:
                    tier = (tier - 1.0) / 3.0
                answers[qid] = _answer_score(qid, tier, 0.85)
                hard_rule = True
            elif qid.startswith("memory_") or decision_class == "memory_relevance":
                excerpt = str(state.get("excerpts", {}).get(qid, "") if isinstance(state.get("excerpts"), dict) else "")
                if not excerpt:
                    excerpt = str(state.get("candidate_excerpt") or state.get(qid) or "")
                answers[qid] = _answer_score(qid, _score_memory(prompt, excerpt), 0.7)
            else:
                answers[qid] = _answer_score(qid, (question.min_score + question.max_score) / 2.0, 0.4)
        elif question.type == "boolean":
            if qid in {"approval_needed"} or decision_class == "approval_signal":
                if policy_deny:
                    answers[qid] = _answer_bool(qid, False, 1.0)
                    hard_rule = True
                elif policy_requires:
                    answers[qid] = _answer_bool(qid, True, 1.0)
                    hard_rule = True
                else:
                    answers[qid] = _answer_bool(qid, False, 0.6)
            elif qid in {"escalate"} or decision_class == "complexity_escalation":
                answers[qid] = _answer_bool(qid, local_complexity_tier(prompt) >= 3, 0.75)
            elif qid in {"done", "block"}:
                answers[qid] = _answer_bool(qid, bool(state.get(qid)), 0.7)
            elif qid == "cancel" or decision_class == "harm_veto":
                if _OBVIOUS_HARM.search(prompt):
                    answers[qid] = _answer_bool(qid, True, 1.0)
                    hard_rule = True
                else:
                    answers[qid] = _answer_bool(qid, False, 0.4)
            else:
                answers[qid] = _answer_bool(qid, False, 0.5)
        else:  # noul
            if qid in {"approval_needed"} or decision_class == "approval_signal":
                if policy_deny:
                    answers[qid] = _answer_noul(qid, 0.0, 1.0)
                    hard_rule = True
                elif policy_requires:
                    answers[qid] = _answer_noul(qid, 1.0, 1.0)
                    hard_rule = True
                else:
                    answers[qid] = _answer_noul(qid, 0.2, 0.6)
            elif qid in {"escalate"}:
                answers[qid] = _answer_noul(qid, 1.0 if local_complexity_tier(prompt) >= 3 else 0.15, 0.75)
            elif qid == "cancel" or decision_class == "harm_veto":
                if _OBVIOUS_HARM.search(prompt):
                    answers[qid] = _answer_noul(qid, 1.0, 1.0)
                    hard_rule = True
                else:
                    answers[qid] = _answer_noul(qid, 0.0, 0.4)
            else:
                answers[qid] = _answer_noul(qid, 0.5, 0.4)

    elapsed = (time.perf_counter() - started) * 1000.0
    return DecisionResult(
        answers=answers,
        source="rules",
        decision_class=decision_class,
        provider="rules",
        provider_version=VERSION,
        model=VERSION,
        fallback_used=False,
        latency=LatencyBreakdown(inference_ms=elapsed, total_ms=elapsed),
        hard_rule=hard_rule,
    )
