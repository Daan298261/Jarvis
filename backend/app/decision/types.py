"""Provider-neutral System-One / Reflex typed questions and answers (RFC-0171)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

QuestionType = Literal["choice", "score", "boolean"]
PrivacyMode = Literal["local_only", "cloud_ok", "deny_cloud"]
DecisionSource = Literal["rules", "laya", "jev", "generative_fallback", "cache", "deadline_fallback"]

DECISION_CLASSES = frozenset(
    {
        "persona_model_routing",
        "tool_shortlist",
        "tool_selection",
        "complexity_escalation",
        "memory_relevance",
        "evidence_relevance",
        "workflow_branch",
        "retry_stop",
        "verifier_score",
        "notification_relevance",
        "browser_operation_target",
        "artifact_classification",
        "source_prioritization",
        "risk_signal",
        "speak_class",
        "approval_signal",
        "probe",
        "generic",
    }
)


@dataclass(frozen=True)
class Question:
    """One bounded typed judgment. Never open-ended generation."""

    id: str
    type: QuestionType
    prompt: str
    choices: tuple[str, ...] = ()
    score_min: float = 0.0
    score_max: float = 1.0
    pure: bool = True  # idempotent → eligible for short TTL cache

    def to_wire(self) -> dict[str, Any]:
        if self.type == "choice":
            return {"type": "choice", "choices": list(self.choices), "question": self.prompt}
        if self.type == "score":
            return {"type": "score", "question": self.prompt}
        return {"type": "noul", "question": self.prompt}


@dataclass(frozen=True)
class Answer:
    question_id: str
    type: QuestionType
    value: Any
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question_id": self.question_id,
            "type": self.type,
            "value": self.value,
            "confidence": self.confidence,
        }
        return payload


@dataclass
class LatencyBreakdown:
    queue_ms: float = 0.0
    serialization_ms: float = 0.0
    network_ms: float = 0.0
    inference_ms: float = 0.0
    total_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_ms": round(self.queue_ms, 3),
            "serialization_ms": round(self.serialization_ms, 3),
            "network_ms": round(self.network_ms, 3),
            "inference_ms": round(self.inference_ms, 3),
            "total_ms": round(self.total_ms, 3),
        }


@dataclass
class DecisionResult:
    answers: dict[str, Answer]
    source: DecisionSource
    decision_class: str
    provider: str
    provider_version: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    deadline_hit: bool = False
    latency: LatencyBreakdown = field(default_factory=LatencyBreakdown)
    batch_size: int = 1
    cached: bool = False
    audited: bool = True

    def value(self, question_id: str, default: Any = None) -> Any:
        answer = self.answers.get(question_id)
        return default if answer is None else answer.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "answers": {qid: ans.to_dict() for qid, ans in self.answers.items()},
            "source": self.source,
            "decision_class": self.decision_class,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "deadline_hit": self.deadline_hit,
            "latency": self.latency.to_dict(),
            "batch_size": self.batch_size,
            "cached": self.cached,
        }


@dataclass(frozen=True)
class DecideRequest:
    state: dict[str, Any]
    questions: tuple[Question, ...]
    decision_class: str
    deadline_ms: int = 100
    privacy: PrivacyMode = "local_only"
