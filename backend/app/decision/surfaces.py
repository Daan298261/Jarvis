"""Typed Reflex surfaces for hot-path decision classes (RFC-0171).

Browser operation/target is a typed decision helper only — full fast loop is RFC-0172.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from .reflex import decide
from .types import Answer, DecisionResult, DecisionSource, LatencyBreakdown, PrivacyMode, Question

log = logging.getLogger("jarvis.decision.surfaces")


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


@dataclass(frozen=True)
class PersonaIntentDecision:
    """RFC-0218 S1: which persona should run this turn.

    ``to`` equals ``current`` when the turn stays. ``reason`` is ``"explicit_name"``,
    ``"intent"`` for a switch, else why it stayed (``"locked"``, ``"no_intent"``,
    ``"below_floor"``, ``"already_active"``, ``"deadline_fallback"``).
    ``"no_current_persona"`` has empty ``current``/``to``: no switch is possible.
    """

    current: str
    to: str
    reason: str
    decision_source: DecisionSource
    confidence: float
    reflex: DecisionResult | None = None

    @property
    def switch(self) -> bool:
        return self.to != self.current

    def as_dict(self) -> dict[str, Any]:
        return {
            "from": self.current,
            "to": self.to,
            "switch": self.switch,
            "reason": self.reason,
            "decision_source": self.decision_source,
            "confidence": round(float(self.confidence), 3),
        }


def persona_intent_question() -> Question:
    from .adapters.rules import PERSONA_STAY
    from ..persona.named_persona import CATALOG

    ids = tuple(CATALOG)
    return Question(
        id="persona_intent",
        type="choice",
        decision_class="persona_intent_switch",
        prompt="Which ANZU persona should handle this turn? Choose stay unless a new task clearly fits a specialist.",
        choices=(PERSONA_STAY, *ids),
        descriptions=(
            "stay on the current persona: chit-chat, thanks, acknowledgement, or no specialist fit",
            *(f"{CATALOG[pid].label}: {CATALOG[pid].role}" for pid in ids),
        ),
    )


def persona_intent_stay(current: str, *, reason: str, source: DecisionSource, confidence: float = 1.0,
                        reflex: DecisionResult | None = None) -> PersonaIntentDecision:
    return PersonaIntentDecision(current, current, reason, source, confidence, reflex)


@dataclass(frozen=True)
class PersonaIntentPrecheck:
    """What RFC-0218 settles *before* the single owner-turn ``decide()``.

    ``decision`` is final when set (no current persona, explicit name, lock);
    otherwise ``question`` joins the owner-turn questions and
    :func:`persona_intent_from_result` applies floor/stay afterwards.
    """

    current: str
    addressed_current: bool = False
    decision: PersonaIntentDecision | None = None

    @property
    def question(self) -> Question | None:
        return None if self.decision is not None else persona_intent_question()


def persona_intent_precheck(user_message: str, *, current_persona: str, locked: bool) -> PersonaIntentPrecheck:
    """Precedence before decide(): explicit roster name > manual lock.

    A manual pin is the owner's explicit selection with the lock setting on
    (RFC-0218 terms), so ``locked`` is what holds the persona. ``pinned`` alone
    (e.g. docked on the HUD) does not block intent; it is passed to providers as
    context. An explicit name always wins. No I/O: safe inside the 50 ms window.
    """
    from .adapters.rules import explicit_persona_name
    from ..persona.named_persona import CATALOG

    current = (current_persona or "").strip().lower()
    if current not in CATALOG:
        # No (or unknown) current persona: there is nothing to switch *from*, so the
        # turn cannot auto-switch. Reported, not defaulted: S2 activates nothing.
        log.warning("persona_intent_switch: no valid current persona (%r); not switching", current_persona)
        return PersonaIntentPrecheck("", decision=PersonaIntentDecision("", "", "no_current_persona", "rules", 1.0))
    explicit = explicit_persona_name(user_message)
    # Naming the persona that is already active is addressing it ("Anzu, write me a
    # script" → enki), not a pin: intent still decides, and a stay reports
    # "already_active" instead of "no_intent".
    addressed_current = explicit == current
    if explicit and not addressed_current:
        return PersonaIntentPrecheck(current, decision=PersonaIntentDecision(current, explicit, "explicit_name", "rules", 1.0))
    if locked:
        return PersonaIntentPrecheck(current, decision=persona_intent_stay(current, reason="locked", source="rules"))
    return PersonaIntentPrecheck(current, addressed_current=addressed_current)


def persona_intent_from_result(
    precheck: PersonaIntentPrecheck,
    result: DecisionResult,
    *,
    floor: float,
) -> PersonaIntentDecision:
    """Floor/stay handling on the shared owner-turn ``decide()`` result."""
    from .adapters.rules import PERSONA_STAY

    if precheck.decision is not None:
        return precheck.decision
    current = precheck.current
    if result.fallback_used and (
        result.source == "deadline_fallback" and "deadline" in (result.fallback_reason or "").lower()
    ):
        return persona_intent_stay(current, reason="deadline_fallback", source="deadline_fallback",
                                   confidence=0.0, reflex=result)
    question = precheck.question
    answer = result.answers.get(question.id)
    if answer is None or answer.type != "choice" or answer.value not in question.choices:
        return persona_intent_stay(current, reason="no_intent", source=result.source, reflex=result)
    confidence = float(answer.confidence or 0.0)
    pick = str(answer.value)
    if pick in {PERSONA_STAY, current}:
        return persona_intent_stay(current, reason="already_active" if precheck.addressed_current else "no_intent",
                                   source=result.source, confidence=confidence, reflex=result)
    if confidence < floor:
        return persona_intent_stay(current, reason="below_floor", source=result.source,
                                   confidence=confidence, reflex=result)
    return PersonaIntentDecision(current, pick, "intent", result.source, confidence, result)


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


ARBITRATION_DEADLINE_MS = 50.0
ARBITRATION_DEADLINE_S = 0.05
ARBITRATION_CHOICES = ("keep_front", "keep_worker", "append_novel")
ARBITRATION_QUESTIONS: list[Question] = [
    Question(
        id="disposition",
        type="choice",
        prompt="How should the front-lane answer and the worker-lane answer become one owner-facing turn?",
        choices=ARBITRATION_CHOICES,
        descriptions=(
            "Keep the front line; drop a worker paraphrase",
            "Keep the worker line; it already contains the front line or corrects it",
            "Keep the front line, then append worker sentences that add new information",
        ),
    )
]


def _arbitration_state(
    *,
    user_message: str,
    front_text: str,
    worker_text: str,
    front_action: str,
    front_spoken: bool,
    reply_shape: str,
) -> dict[str, Any]:
    return {
        "user_message": user_message,
        "front_text": front_text,
        "worker_text": worker_text,
        "front_action": front_action,
        "front_spoken": bool(front_spoken),
        "reply_shape": reply_shape,
    }


def _arbitration_deadline_fallback(
    *,
    user_message: str,
    front_text: str,
    worker_text: str,
    front_action: str,
    front_spoken: bool,
    reply_shape: str,
    reason: str,
    spent_ms: float,
) -> DecisionResult:
    from .adapters import rules
    from . import audit, metrics

    base = rules.decide(
        state=_arbitration_state(
            user_message=user_message,
            front_text=front_text,
            worker_text=worker_text,
            front_action=front_action,
            front_spoken=front_spoken,
            reply_shape=reply_shape,
        ),
        questions=ARBITRATION_QUESTIONS,
        decision_class="arbitration",
        deadline_ms=ARBITRATION_DEADLINE_MS,
    )
    result = DecisionResult(
        answers=base.answers,
        source="deadline_fallback",
        decision_class="arbitration",
        provider="rules",
        provider_version=base.provider_version,
        model=base.model,
        fallback_used=True,
        fallback_reason=reason,
        fallback_source="rules",
        latency=LatencyBreakdown(total_ms=spent_ms, inference_ms=base.latency.inference_ms),
        hard_rule=base.hard_rule,
        meta={"deadline_fallback": True, "arbitration": True},
    )
    metrics.record(result)
    audit.record_event("reflex_deadline_fallback", result.as_dict())
    return result


def arbitrate_front_and_worker(
    *,
    user_message: str,
    front_text: str,
    worker_text: str,
    front_action: str = "",
    front_spoken: bool = False,
    reply_shape: str = "",
    decision_tier: str = "local",
    deadline_ms: float = ARBITRATION_DEADLINE_MS,
    privacy: PrivacyMode | None = None,
) -> DecisionResult:
    """One Reflex decide() for how front + worker become one owner-facing turn."""
    mode = privacy if privacy is not None else privacy_for_tier(decision_tier)
    return decide(
        _arbitration_state(
            user_message=user_message,
            front_text=front_text,
            worker_text=worker_text,
            front_action=front_action,
            front_spoken=front_spoken,
            reply_shape=reply_shape,
        ),
        ARBITRATION_QUESTIONS,
        "arbitration",
        deadline_ms,
        mode,
    )


async def arbitrate_front_and_worker_bounded(
    *,
    user_message: str,
    front_text: str,
    worker_text: str,
    front_action: str = "",
    front_spoken: bool = False,
    reply_shape: str = "",
    decision_tier: str = "local",
    deadline_ms: float = ARBITRATION_DEADLINE_MS,
    privacy: PrivacyMode | None = None,
) -> DecisionResult:
    """Same as ``arbitrate_front_and_worker`` with a 50 ms wall-clock cap off the loop."""
    started = time.perf_counter()
    timeout_s = max(0.001, float(deadline_ms) / 1000.0)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                arbitrate_front_and_worker,
                user_message=user_message,
                front_text=front_text,
                worker_text=worker_text,
                front_action=front_action,
                front_spoken=front_spoken,
                reply_shape=reply_shape,
                decision_tier=decision_tier,
                deadline_ms=deadline_ms,
                privacy=privacy,
            ),
            timeout=timeout_s,
        )
    except TimeoutError:
        spent = (time.perf_counter() - started) * 1000.0
        log.info("Arbitration reflex exceeded 50 ms; using rules deadline fallback")
        return _arbitration_deadline_fallback(
            user_message=user_message,
            front_text=front_text,
            worker_text=worker_text,
            front_action=front_action,
            front_spoken=front_spoken,
            reply_shape=reply_shape,
            reason="outer wait_for exceeded 50 ms",
            spent_ms=spent,
        )
    except Exception:
        spent = (time.perf_counter() - started) * 1000.0
        log.warning("Arbitration reflex unavailable; using rules deadline fallback", exc_info=True)
        return _arbitration_deadline_fallback(
            user_message=user_message,
            front_text=front_text,
            worker_text=worker_text,
            front_action=front_action,
            front_spoken=front_spoken,
            reply_shape=reply_shape,
            reason="arbitration provider error",
            spent_ms=spent,
        )
