"""Provider-neutral System-One / Reflex types (RFC-0171)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

QuestionType = Literal["choice", "score", "boolean", "noul"]
PrivacyMode = Literal["local_only", "allow_cloud", "require_local"]
DecisionSource = Literal["rules", "laya", "jev", "generative", "cache", "deadline_fallback"]
ProviderName = Literal["rules", "laya", "jev", "generative"]

# Decision classes that may use Reflex. Open-ended generation stays off this list.
REFLEX_DECISION_CLASSES: frozenset[str] = frozenset(
    {
        "persona_model_routing",
        "tool_shortlist",
        "tool_selection",
        "complexity_escalation",
        "memory_relevance",
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
        "turn_batch",
        "probe",
    }
)

# Never final permission authority — risk_signal / approval_signal are advisory only.
POLICY_HARDENED_CLASSES: frozenset[str] = frozenset(
    {
        "approval_signal",
        "risk_signal",
    }
)


@dataclass(frozen=True)
class Question:
    """Typed bounded question. Boolean maps to noul semantics for providers that lack bool."""

    id: str
    type: QuestionType
    prompt: str
    choices: tuple[str, ...] = ()
    min_score: float = 0.0
    max_score: float = 1.0

    def to_provider_dict(self) -> dict[str, Any]:
        if self.type == "choice":
            return {
                "type": "choice",
                "choices": list(self.choices),
                "question": self.prompt,
            }
        if self.type == "score":
            return {
                "type": "score",
                "question": self.prompt,
                "min": self.min_score,
                "max": self.max_score,
            }
        if self.type == "boolean":
            return {
                "type": "noul",
                "question": self.prompt,
            }
        return {"type": "noul", "question": self.prompt}


@dataclass(frozen=True)
class Answer:
    question_id: str
    type: QuestionType
    value: Any
    confidence: float | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "value": self.value,
            "confidence": self.confidence,
        }
        if self.type == "choice":
            payload["choice"] = self.value
        elif self.type == "score":
            payload["score"] = self.value
        elif self.type in {"boolean", "noul"}:
            payload["noul"] = float(self.value) if self.value is not None else None
            if self.type == "boolean":
                payload["boolean"] = bool(self.value) if not isinstance(self.value, bool) else self.value
        return payload


@dataclass
class LatencyBreakdown:
    queue_ms: float = 0.0
    serialization_ms: float = 0.0
    network_ms: float = 0.0
    inference_ms: float = 0.0
    total_ms: float = 0.0

    def as_dict(self) -> dict[str, float]:
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
    provider: ProviderName
    provider_version: str = ""
    model: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    fallback_source: str = ""
    cached: bool = False
    latency: LatencyBreakdown = field(default_factory=LatencyBreakdown)
    hard_rule: bool = False
    request_id: str = ""
    fixture: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "answers": {qid: ans.as_dict() for qid, ans in self.answers.items()},
            "source": self.source,
            "decision_class": self.decision_class,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "model": self.model,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "fallback_source": self.fallback_source,
            "cached": self.cached,
            "latency": self.latency.as_dict(),
            "hard_rule": self.hard_rule,
            "request_id": self.request_id,
            "fixture": self.fixture,
            "meta": dict(self.meta),
        }


def normalize_questions(
    questions: dict[str, Any] | list[Question] | tuple[Question, ...],
) -> list[Question]:
    if isinstance(questions, (list, tuple)):
        out = list(questions)
        if not out:
            raise ValueError("questions must not be empty")
        return out
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a non-empty map or list")
    out: list[Question] = []
    for qid, raw in questions.items():
        if isinstance(raw, Question):
            out.append(raw if raw.id == qid else Question(
                id=qid,
                type=raw.type,
                prompt=raw.prompt,
                choices=raw.choices,
                min_score=raw.min_score,
                max_score=raw.max_score,
            ))
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"question {qid!r} must be a dict or Question")
        qtype = str(raw.get("type") or "").strip().lower()
        if qtype not in {"choice", "score", "boolean", "noul"}:
            raise ValueError(f"question {qid!r} has unsupported type {qtype!r}")
        choices = tuple(str(c) for c in (raw.get("choices") or []) if str(c).strip())
        if qtype == "choice" and not choices:
            raise ValueError(f"choice question {qid!r} requires choices")
        prompt = str(raw.get("question") or raw.get("prompt") or qid)
        out.append(
            Question(
                id=str(qid),
                type=qtype,  # type: ignore[arg-type]
                prompt=prompt,
                choices=choices,
                min_score=float(raw.get("min", raw.get("min_score", 0.0))),
                max_score=float(raw.get("max", raw.get("max_score", 1.0))),
            )
        )
    return out


def questions_to_provider_map(questions: list[Question]) -> dict[str, Any]:
    return {q.id: q.to_provider_dict() for q in questions}


def compact_state(state: dict[str, Any] | None, *, max_chars: int = 2400) -> dict[str, Any]:
    """Compact projection — never ship full transcripts or tool catalogs."""
    if not state:
        return {}
    out: dict[str, Any] = {}
    for key, value in state.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str):
            out[key] = value[:800]
        elif isinstance(value, (list, tuple)):
            capped = list(value)[:64]
            out[key] = [
                (item[:120] if isinstance(item, str) else item) for item in capped
            ]
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = compact_state(value, max_chars=max_chars // 2)
        else:
            out[key] = str(value)[:200]
    encoded = str(out)
    if len(encoded) > max_chars:
        # Drop largest string fields until under budget.
        for key in sorted(out.keys(), key=lambda k: len(str(out[k])), reverse=True):
            if len(str(out)) <= max_chars:
                break
            if isinstance(out[key], str) and len(out[key]) > 80:
                out[key] = out[key][:80]
    return out
