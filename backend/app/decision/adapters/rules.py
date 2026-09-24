"""Deterministic rules adapter — always first (RFC-0171)."""

from __future__ import annotations

import re
from typing import Any

from ..types import Answer, DecideRequest, Question
from .base import ReflexAdapter

_SOCIAL = re.compile(r"(?i)\b(hello|hi\b|hey|thanks|thank you|how are you)\b")
_TECH = re.compile(r"(?i)\b(traceback|error|debug|implement|refactor|pytest|code)\b")


class RulesAdapter:
    name = "rules"

    def available(self, request: DecideRequest) -> tuple[bool, str]:
        return True, ""

    def decide(self, request: DecideRequest) -> tuple[dict[str, Answer], str, float]:
        answers: dict[str, Answer] = {}
        for question in request.questions:
            value = self._answer_one(request, question)
            if value is None:
                continue
            answers[question.id] = value
        # Rules only claim full coverage when every question was answered.
        return answers, "rules-v1", 0.05

    def _answer_one(self, request: DecideRequest, question: Question) -> Answer | None:
        state = request.state
        text = str(state.get("user_message") or state.get("prompt") or state.get("query") or "")
        decision_class = request.decision_class

        if question.type == "choice":
            return self._choice(decision_class, question, state, text)
        if question.type == "score":
            return self._score(decision_class, question, state, text)
        return self._boolean(decision_class, question, state, text)

    def _choice(self, decision_class: str, question: Question, state: dict[str, Any], text: str) -> Answer | None:
        choices = list(question.choices)
        if not choices:
            return None
        if decision_class in {"tool_selection", "tool_shortlist", "complexity_escalation"}:
            if question.id == "tool_select" or decision_class in {"tool_selection", "tool_shortlist"}:
                lowered = text.lower()
                for choice in choices:
                    if choice == "none":
                        continue
                    if choice.lower() in lowered or choice.lower().replace("_", " ") in lowered:
                        # Soft — Laya/Jev may refine.
                        return Answer(question.id, "choice", choice, 0.88)
                ranked = state.get("candidate_tools") or state.get("shortlist") or []
                for name in ranked:
                    if name in choices:
                        return Answer(question.id, "choice", name, 0.75)
                if "none" in choices:
                    return Answer(question.id, "choice", "none", 0.65)
                return Answer(question.id, "choice", choices[0], 0.55)
        if decision_class == "persona_model_routing":
            preferred = str(state.get("preferred_profile") or state.get("local_profile") or "")
            if preferred in choices:
                # Preferred profile is a hard local lock.
                return Answer(question.id, "choice", preferred, 0.99)
            if "balanced" in choices:
                return Answer(question.id, "choice", "balanced", 0.7)
            return Answer(question.id, "choice", choices[0], 0.6)
        if decision_class in {"speak_class", "complexity_escalation"} and question.id == "speak_class":
            if _TECH.search(text) and "technical" in choices:
                return Answer(question.id, "choice", "technical", 0.99)
            if _SOCIAL.search(text) and "social" in choices:
                return Answer(question.id, "choice", "social", 0.9)
            if "technical" in choices:
                return Answer(question.id, "choice", "technical", 0.6)
        if decision_class == "browser_operation_target":
            op = str(state.get("suggested_operation") or "").strip()
            if question.id.endswith("operation") or question.id == "operation":
                if op in choices:
                    return Answer(question.id, "choice", op, 0.85)
            target = str(state.get("suggested_target_id") or "").strip()
            if question.id.endswith("target") or question.id == "target_id":
                if target in choices:
                    return Answer(question.id, "choice", target, 0.85)
            if "noop" in choices:
                return Answer(question.id, "choice", "noop", 0.5)
            if "none" in choices:
                return Answer(question.id, "choice", "none", 0.5)
            return Answer(question.id, "choice", choices[0], 0.4)
        # Generic: first choice with weak confidence — incomplete for provider routing.
        return None

    def _score(self, decision_class: str, question: Question, state: dict[str, Any], text: str) -> Answer | None:
        if decision_class in {"memory_relevance", "evidence_relevance"}:
            # Batched same-state questions: rel_0..rel_N map to candidates[i].
            if question.id.startswith("rel_"):
                try:
                    index = int(question.id.split("_", 1)[1])
                except (TypeError, ValueError):
                    index = -1
                candidates = state.get("candidates") or []
                excerpt = ""
                if 0 <= index < len(candidates) and isinstance(candidates[index], dict):
                    excerpt = str(candidates[index].get("excerpt") or "")
                tokens = {t for t in str(state.get("query") or text).lower().split() if len(t) > 2}
                if not tokens:
                    return Answer(question.id, "score", 0.0, 0.9)
                hay = excerpt.lower()
                hits = sum(1 for t in tokens if t in hay)
                score = min(1.0, hits / max(3, min(8, len(tokens))))
                return Answer(question.id, "score", score, 0.88)
            excerpt = str(state.get("excerpt") or state.get("candidate_text") or "")
            tokens = {t for t in text.lower().split() if len(t) > 2}
            if not tokens:
                return Answer(question.id, "score", 0.0, 0.9)
            hay = excerpt.lower()
            hits = sum(1 for t in tokens if t in hay)
            score = min(1.0, hits / max(3, min(8, len(tokens))))
            return Answer(question.id, "score", score, 0.9)
        if decision_class == "complexity_escalation" and question.id in {"complexity_tier", "complexity"}:
            local = state.get("local_complexity")
            if local is not None:
                try:
                    return Answer(question.id, "score", float(local), 0.99)
                except (TypeError, ValueError):
                    pass
        if "local_score" in state:
            try:
                return Answer(question.id, "score", float(state["local_score"]), 0.95)
            except (TypeError, ValueError):
                pass
        return None

    def _boolean(self, decision_class: str, question: Question, state: dict[str, Any], text: str) -> Answer | None:
        if decision_class == "complexity_escalation" and question.id in {"escalate", "needs_escalate"}:
            if state.get("local_escalate"):
                return Answer(question.id, "boolean", 1.0, 0.99)
            return Answer(question.id, "boolean", 0.0, 0.8)
        if question.id == "approval_needed" or decision_class == "approval_signal":
            if state.get("policy_deny"):
                return Answer(question.id, "boolean", 0.0, 1.0)
            if state.get("policy_requires_approval"):
                return Answer(question.id, "boolean", 1.0, 1.0)
            return Answer(question.id, "boolean", 0.0, 0.8)
        if decision_class in {"memory_relevance", "evidence_relevance"} and question.id.startswith("keep_"):
            score = state.get("local_relevance")
            if score is not None:
                try:
                    return Answer(question.id, "boolean", 1.0 if float(score) >= 0.45 else 0.0, 0.9)
                except (TypeError, ValueError):
                    pass
        if decision_class == "browser_operation_target" and question.id in {"done", "block"}:
            if question.id in state:
                return Answer(question.id, "boolean", 1.0 if state[question.id] else 0.0, 0.95)
        return None


ADAPTER: ReflexAdapter = RulesAdapter()
