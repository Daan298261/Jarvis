"""RFC-0206: one Reflex decide() for every owner turn (route + reply shape)."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..agent.planning import (
    CONVERSATION_CLASS,
    DIRECT_LOOKUP,
    DIRECT_REPLY,
    MANAGED_TASK,
    RequestRoute,
    classify_task,
    is_weather_query,
    lta_protected_folder_path,
    requests_agent_tools,
    route_request,
    simple_app_control,
    simple_file_control,
)
from .reflex import decide
from .surfaces import privacy_for_tier
from .types import Answer, DecisionResult, LatencyBreakdown, Question

log = logging.getLogger("jarvis.decision.owner_turn")

OWNER_TURN_DEADLINE_MS = 50.0
OWNER_TURN_DEADLINE_S = 0.05
ROUTE_CONFIDENCE_FLOOR = 0.75

REPLY_SHAPES = ("literal", "self_status", "social", "ack", "clarify", "handoff")
REQUEST_ROUTES = (DIRECT_REPLY, DIRECT_LOOKUP, MANAGED_TASK)

OWNER_TURN_QUESTIONS: list[Question] = [
    Question(
        id="request_route",
        type="choice",
        prompt="Which parser should handle this user request?",
        choices=REQUEST_ROUTES,
        descriptions=(
            "Conversation: answer a greeting or knowledge question without tools",
            "Weather lookup: retrieve current weather or forecast",
            "Action: open an app, inspect or change files, browse, code, or execute a task",
        ),
    ),
    Question(
        id="reply_shape",
        type="choice",
        prompt="What shape should the front reply take?",
        choices=REPLY_SHAPES,
        descriptions=(
            "Owner asked for an exact word or quoted span; output that text only",
            "Owner asked about ANZU itself; answer from the live self snapshot",
            "Greeting or casual chat that the front lane can finish",
            "Acknowledge and continue; the worker lane must run",
            "Ask one short clarifying question; do not start the worker",
            "Hand off to the worker for a real task",
        ),
    ),
]

# Closed literal patterns. Longer forms first so "say only the word X" wins.
_LITERAL_WORD = re.compile(
    r"(?i)\b(?:say only the word|say only|reply with only|just say)\s+([A-Za-z0-9-]{1,80})\b"
)
_LITERAL_QUOTED = re.compile(
    r'(?i)\b(?:respond|reply) with exactly\s+"([^"]{1,80})"'
)
_VAGUE_PROMPT = re.compile(
    r"(?i)^(do it|fix it|handle it|you know|the thing|this|that|please|go|ok then)\s*[.!?]*$"
)
_TRIVIAL_CHAT = re.compile(
    r"(?i)\b("
    r"hi|hello|hey|yo|thanks|thank you|cheers|bye|goodbye|"
    r"good\s+(?:morning|afternoon|evening|night)|"
    r"how are you|how(?:'s| is) it going|what'?s up|"
    r"tell me a (?:quick )?hello"
    r")\b"
)
_NEEDS_STRONGER = re.compile(
    r"(?i)\b("
    r"refactor|security|hexstrike|vulnerability|cve-|forensic|"
    r"architecture|codebase|implement|deploy|migrate|pytest|"
    r"debug this|source code|pull request"
    r")\b"
)
_LIVE_FACT_HINT = re.compile(
    r"(?i)\b(weather|forecast|news|score|price|stock|latest|right now|currently|cve-)\b"
)
_SELF_STATUS = re.compile(
    r"(?i)\b("
    r"what profile(?: is loaded)?|which profile|loaded profile|"
    r"what model|which model|model alias|what(?:'s| is) loaded|"
    r"who are you|what are you|your (?:name|persona|setup|settings|config|context)|"
    r"active persona|decision tier|front lane|voice profile|"
    r"is (?:the )?(?:vault|laya|jev)|laya (?:installed|warm|enabled)|"
    r"what(?:'s| is) (?:your )?(?:shell|context|verbosity|personality)|"
    r"about (?:yourself|anzu)|anzu superassistant"
    r")\b"
)


@dataclass(frozen=True)
class OwnerTurnDecision:
    """Typed owner-turn routing + front-lane shape (RFC-0206)."""

    route: RequestRoute
    reply_shape: str
    front_action: str
    literal_text: str = ""
    reflex: DecisionResult | None = None
    start_worker: bool = False
    snapshot_covers: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "route_kind": self.route.kind,
            "task_class": self.route.task_class,
            "reply_shape": self.reply_shape,
            "front_action": self.front_action,
            "literal_text": self.literal_text,
            "start_worker": self.start_worker,
            "snapshot_covers": self.snapshot_covers,
            "source": getattr(self.reflex, "source", ""),
            "provider": getattr(self.reflex, "provider", ""),
            "fallback_used": bool(getattr(self.reflex, "fallback_used", False)),
        }


def extract_literal_candidate(user_message: str) -> str:
    """Closed patterns on the raw utterance — run before compact_state."""
    text = user_message or ""
    quoted = _LITERAL_QUOTED.search(text)
    if quoted:
        return quoted.group(1)
    word = _LITERAL_WORD.search(text)
    if word:
        return word.group(1)
    return ""


def is_explicit_action(user_message: str) -> bool:
    return bool(
        requests_agent_tools(user_message)
        or simple_app_control(user_message)
        or simple_file_control(user_message)
        or lta_protected_folder_path(user_message)
    )


def infer_rules_reply_shape(
    user_message: str,
    *,
    baseline_route: str = "",
    literal_candidate: str = "",
) -> str:
    """Deterministic reply_shape used by the rules adapter and as the floor fallback."""
    text = (user_message or "").strip()
    if not text:
        return "ack"
    if (literal_candidate or "").strip():
        return "literal"
    lowered = text.lower().strip()
    if is_explicit_action(text):
        return "handoff"
    if _VAGUE_PROMPT.match(lowered):
        return "clarify"
    if is_weather_query(text) or _LIVE_FACT_HINT.search(lowered):
        return "ack"
    if _SELF_STATUS.search(text):
        return "self_status"
    kind = (baseline_route or "").strip() or route_request(text).kind
    if kind == MANAGED_TASK:
        return "handoff" if _NEEDS_STRONGER.search(lowered) else "ack"
    if kind == DIRECT_LOOKUP:
        return "ack"
    if _TRIVIAL_CHAT.search(lowered) or kind == DIRECT_REPLY:
        return "social"
    return "ack"


def front_action_for_shape(
    reply_shape: str,
    *,
    snapshot_covers: bool = False,
) -> str:
    """Map reply_shape onto the existing FRONT_ACTIONS set. No sixth action."""
    if reply_shape == "literal":
        return "final_basic"
    if reply_shape == "self_status":
        return "final_basic" if snapshot_covers else "ack_continue"
    if reply_shape == "social":
        return "final_basic"
    if reply_shape == "clarify":
        return "ask_clarification"
    if reply_shape == "handoff":
        return "handoff_notice"
    if reply_shape == "ack":
        return "ack_continue"
    return "ack_continue"


def _resolved_tier(decision_tier: str, settings: Any | None) -> str:
    raw = str(decision_tier or "").strip().lower()
    if not raw and settings is not None:
        raw = str(getattr(getattr(settings, "decision", None), "tier", "") or "").strip().lower()
    if raw not in {"local", "jev_optional", "jev_plus"}:
        return "local"
    return raw


def _answer_choice(result: DecisionResult, question_id: str) -> Answer | None:
    answer = result.answers.get(question_id)
    if answer is None or answer.type != "choice":
        return None
    return answer


def _snapshot_covers(user_message: str, settings: Any | None, inference_state: Any | None) -> bool:
    if settings is None:
        return False
    try:
        from ..agent.self_knowledge import snapshot_covers_question

        return snapshot_covers_question(user_message, settings, inference_state)
    except Exception:
        return False


def _apply_floors(
    *,
    user_message: str,
    baseline: RequestRoute,
    literal: str,
    result: DecisionResult,
    settings: Any | None,
    inference_state: Any | None,
) -> OwnerTurnDecision:
    route_answer = _answer_choice(result, "request_route")
    shape_answer = _answer_choice(result, "reply_shape")
    rules_shape = infer_rules_reply_shape(
        user_message,
        baseline_route=baseline.kind,
        literal_candidate=literal,
    )

    if (
        result.fallback_used
        or route_answer is None
        or (route_answer.confidence or 0) < ROUTE_CONFIDENCE_FLOOR
        or route_answer.value not in REQUEST_ROUTES
    ):
        route_kind = baseline.kind
    else:
        route_kind = str(route_answer.value)

    if shape_answer is None or shape_answer.value not in REPLY_SHAPES:
        reply_shape = rules_shape
    else:
        reply_shape = str(shape_answer.value)

    if is_explicit_action(user_message):
        route_kind = MANAGED_TASK
        reply_shape = "handoff"
    if is_weather_query(user_message):
        route_kind = DIRECT_LOOKUP
        if reply_shape in {"social", "literal", "self_status"}:
            reply_shape = "ack"
    if literal:
        reply_shape = "literal"

    if route_kind == DIRECT_LOOKUP:
        task_class = CONVERSATION_CLASS
    elif route_kind == DIRECT_REPLY:
        task_class = CONVERSATION_CLASS if baseline.kind != MANAGED_TASK else baseline.task_class
        if baseline.kind == MANAGED_TASK and not is_explicit_action(user_message):
            # Confidence-accepted direct_reply may stand; the action floor already ran.
            task_class = CONVERSATION_CLASS
    else:
        route_kind = MANAGED_TASK
        task_class = classify_task(user_message) if baseline.kind != MANAGED_TASK else baseline.task_class
        if not task_class:
            task_class = classify_task(user_message)

    covers = False
    if reply_shape == "self_status":
        covers = _snapshot_covers(user_message, settings, inference_state)
    action = front_action_for_shape(reply_shape, snapshot_covers=covers)
    start_worker = action in {"ack_continue", "handoff_notice", "silent_skip"}
    return OwnerTurnDecision(
        route=RequestRoute(route_kind, task_class),
        reply_shape=reply_shape,
        front_action=action,
        literal_text=literal,
        reflex=result,
        start_worker=start_worker,
        snapshot_covers=covers,
        meta={"rules_shape": rules_shape},
    )


def _deadline_rules_result(
    *,
    user_message: str,
    baseline: RequestRoute,
    literal: str,
    decision_tier: str,
    reason: str,
    spent_ms: float,
) -> DecisionResult:
    from .adapters import rules

    state = {
        "user_message": user_message,
        "baseline_route": baseline.kind,
        "literal_candidate": literal,
        "decision_tier": decision_tier,
    }
    base = rules.decide(
        state=state,
        questions=OWNER_TURN_QUESTIONS,
        decision_class="request_routing",
        deadline_ms=OWNER_TURN_DEADLINE_MS,
    )
    result = DecisionResult(
        answers=base.answers,
        source="deadline_fallback",
        decision_class="request_routing",
        provider="rules",
        provider_version=base.provider_version,
        model=base.model,
        fallback_used=True,
        fallback_reason=reason,
        fallback_source="rules",
        latency=LatencyBreakdown(total_ms=spent_ms, inference_ms=base.latency.inference_ms),
        hard_rule=base.hard_rule,
        meta={"deadline_fallback": True, "owner_turn": True},
    )
    from . import audit, metrics

    metrics.record(result)
    audit.record_event("reflex_deadline_fallback", result.as_dict())
    return result


def _decide_sync(
    user_message: str,
    baseline: RequestRoute,
    decision_tier: str,
    settings: Any | None,
    inference_state: Any | None,
) -> OwnerTurnDecision:
    literal = extract_literal_candidate(user_message)
    tier = _resolved_tier(decision_tier, settings)
    state = {
        "user_message": user_message,
        "baseline_route": baseline.kind,
        "literal_candidate": literal,
        "decision_tier": tier,
    }
    result = decide(
        state,
        OWNER_TURN_QUESTIONS,
        "request_routing",
        OWNER_TURN_DEADLINE_MS,
        privacy_for_tier(tier),
    )
    return _apply_floors(
        user_message=user_message,
        baseline=baseline,
        literal=literal,
        result=result,
        settings=settings,
        inference_state=inference_state,
    )


def rules_front_action(user_message: str, *, baseline: RequestRoute | None = None) -> str:
    """Rules-only front action for callers that do not yet hold an OwnerTurnDecision."""
    text = (user_message or "").strip()
    if not text:
        return "silent_skip"
    resolved = baseline or route_request(text)
    literal = extract_literal_candidate(text)
    shape = infer_rules_reply_shape(
        text,
        baseline_route=resolved.kind,
        literal_candidate=literal,
    )
    covers = False
    return front_action_for_shape(shape, snapshot_covers=covers)


async def decide_owner_turn(
    user_message: str,
    *,
    baseline: RequestRoute | None = None,
    decision_tier: str = "",
    settings: Any | None = None,
    inference_state: Any | None = None,
) -> OwnerTurnDecision:
    """Mandatory System-One entry for owner chat and agent-loop intake.

    Always calls ``decide()`` with a 50 ms wall-clock cap. A timeout becomes an
    audited ``deadline_fallback`` to the rules classifier — never a skipped call.
    """
    import time

    text = user_message or ""
    resolved_baseline = baseline or route_request(text)
    started = time.perf_counter()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _decide_sync,
                text,
                resolved_baseline,
                decision_tier,
                settings,
                inference_state,
            ),
            timeout=OWNER_TURN_DEADLINE_S,
        )
    except TimeoutError:
        spent = (time.perf_counter() - started) * 1000.0
        log.info("Owner-turn reflex exceeded 50 ms; using rules deadline fallback")
        literal = extract_literal_candidate(text)
        tier = _resolved_tier(decision_tier, settings)
        result = _deadline_rules_result(
            user_message=text,
            baseline=resolved_baseline,
            literal=literal,
            decision_tier=tier,
            reason="outer wait_for exceeded 50 ms",
            spent_ms=spent,
        )
        return _apply_floors(
            user_message=text,
            baseline=resolved_baseline,
            literal=literal,
            result=result,
            settings=settings,
            inference_state=inference_state,
        )
    except Exception:
        spent = (time.perf_counter() - started) * 1000.0
        log.warning("Owner-turn reflex unavailable; using rules deadline fallback", exc_info=True)
        literal = extract_literal_candidate(text)
        tier = _resolved_tier(decision_tier, settings)
        result = _deadline_rules_result(
            user_message=text,
            baseline=resolved_baseline,
            literal=literal,
            decision_tier=tier,
            reason="owner-turn provider error",
            spent_ms=spent,
        )
        return _apply_floors(
            user_message=text,
            baseline=resolved_baseline,
            literal=literal,
            result=result,
            settings=settings,
            inference_state=inference_state,
        )
