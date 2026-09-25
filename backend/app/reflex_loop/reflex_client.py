"""Thin typed client for the RFC-0171 Reflex Lane decide() contract.

Does not reimplement Jev/Laya. When ``app.decision`` exposes the provider-neutral
API, this module forwards to it (preferring ``surfaces.browser_operation_target``
for the op+target path). Otherwise callers get a fail-closed stub that honestly
refuses decisions (tests inject FakeDecideClient).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable
import importlib
import logging

log = logging.getLogger("jarvis.reflex_loop.client")

# Decision class used for browser/computer operation + target selection (RFC-0171).
BROWSER_OP_TARGET_CLASS = "browser_operation_target"
# Pre-land 0172 typo / draft name — mapped to BROWSER_OP_TARGET_CLASS on forward.
_LEGACY_BROWSER_OP_TARGET_CLASS = "browser_computer_op_target"

_PRIVACY_MAP = {
    "local": "local_only",
    "local_only": "local_only",
    "allow_cloud": "allow_cloud",
    "require_local": "require_local",
}


class DecisionClass(str, Enum):
    BROWSER_COMPUTER_OP_TARGET = BROWSER_OP_TARGET_CLASS
    TOOL_SELECTION = "tool_selection"
    ROUTING = "routing"
    MEMORY_RELEVANCE = "memory_relevance"
    WORKFLOW_BRANCH = "workflow_branch"
    RETRY_STOP = "retry_stop"
    VERIFIER_SCORE = "verifier_score"


@dataclass(frozen=True)
class DecisionQuestion:
    """Typed question for the Reflex Lane (choice / score / boolean).

    Local reflex_loop shape uses ``kind`` / ``options``. The forwarder adapts
    these to RFC-0171 ``type`` / ``choices`` when calling ``app.decision``.
    """

    id: str
    kind: str  # "choice" | "score" | "boolean"
    prompt: str
    options: tuple[str, ...] = ()
    min_score: float = 0.0
    max_score: float = 1.0


@dataclass
class DecisionResult:
    ok: bool
    answers: dict[str, Any] = field(default_factory=dict)
    provider: str = "none"
    latency_ms: float = 0.0
    error: str = ""
    confidence: float = 0.0
    source: str = "stub"

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "answers": dict(self.answers),
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "confidence": self.confidence,
            "source": self.source,
        }


@runtime_checkable
class ReflexDecideClient(Protocol):
    def decide(
        self,
        state: dict[str, Any],
        questions: list[DecisionQuestion],
        decision_class: str | DecisionClass,
        *,
        deadline_ms: int = 100,
        privacy: str = "local_only",
    ) -> DecisionResult: ...


def map_privacy(privacy: str) -> str:
    """Map reflex_loop privacy aliases onto RFC-0171 PrivacyMode."""
    key = str(privacy or "local_only").strip().lower()
    return _PRIVACY_MAP.get(key, "local_only")


def map_decision_class(decision_class: str | DecisionClass) -> str:
    """Normalize decision class; map legacy 0172 draft name onto 0171."""
    klass = (
        decision_class.value
        if isinstance(decision_class, DecisionClass)
        else str(decision_class or "").strip()
    )
    if klass == _LEGACY_BROWSER_OP_TARGET_CLASS:
        return BROWSER_OP_TARGET_CLASS
    return klass


def questions_to_0171_map(questions: list[DecisionQuestion]) -> dict[str, Any]:
    """Shape reflex DecisionQuestions as RFC-0171 normalize_questions dict map."""
    out: dict[str, Any] = {}
    for q in questions:
        qtype = str(q.kind or "choice").strip().lower()
        if qtype not in {"choice", "score", "boolean", "noul"}:
            qtype = "choice"
        entry: dict[str, Any] = {
            "type": qtype,
            "prompt": q.prompt,
        }
        if qtype == "choice":
            entry["choices"] = list(q.options)
        if qtype == "score":
            entry["min_score"] = q.min_score
            entry["max_score"] = q.max_score
        out[q.id] = entry
    return out


def _flatten_0171_answers(answers: Any) -> tuple[dict[str, Any], list[float]]:
    flat: dict[str, Any] = {}
    confidences: list[float] = []
    if not isinstance(answers, dict):
        return flat, confidences
    for qid, ans in answers.items():
        if hasattr(ans, "value"):
            flat[str(qid)] = ans.value
            conf = getattr(ans, "confidence", None)
            if conf is not None:
                try:
                    confidences.append(float(conf))
                except (TypeError, ValueError):
                    pass
            continue
        if isinstance(ans, dict):
            if "value" in ans:
                flat[str(qid)] = ans["value"]
            elif "choice" in ans:
                flat[str(qid)] = ans["choice"]
            elif "boolean" in ans:
                flat[str(qid)] = ans["boolean"]
            elif "score" in ans:
                flat[str(qid)] = ans["score"]
            else:
                flat[str(qid)] = ans
            conf = ans.get("confidence")
            if conf is not None:
                try:
                    confidences.append(float(conf))
                except (TypeError, ValueError):
                    pass
            continue
        flat[str(qid)] = ans
    return flat, confidences


def adapt_decision_result(raw: Any) -> DecisionResult:
    """Adapt RFC-0171 DecisionResult (or dict) → reflex_loop DecisionResult."""
    if isinstance(raw, DecisionResult):
        return raw
    if isinstance(raw, dict):
        answers = dict(raw.get("answers") or {})
        # Flatten nested answer dicts if present.
        flat, confidences = _flatten_0171_answers(answers)
        if not flat and answers:
            # Already flat scalars.
            flat = {str(k): v for k, v in answers.items() if not isinstance(v, dict)}
            if not flat:
                flat, confidences = _flatten_0171_answers(answers)
        latency = raw.get("latency_ms")
        if latency is None and isinstance(raw.get("latency"), dict):
            latency = raw["latency"].get("total_ms")
        ok = bool(raw.get("ok", bool(flat)))
        confidence = float(raw.get("confidence") or 0.0)
        if not confidence and confidences:
            confidence = sum(confidences) / len(confidences)
        return DecisionResult(
            ok=ok,
            answers=flat if flat else {str(k): v for k, v in answers.items()},
            provider=str(raw.get("provider") or "decision"),
            latency_ms=float(latency or 0.0),
            error=str(raw.get("error") or ("" if ok else "decision returned no answers")),
            confidence=confidence,
            source=str(raw.get("source") or "app.decision"),
        )

    # Duck-type app.decision.types.DecisionResult (answers are Answer objects; no ok).
    answers_attr = getattr(raw, "answers", None)
    if answers_attr is not None and (
        hasattr(raw, "provider") or hasattr(raw, "source") or hasattr(raw, "decision_class")
    ):
        flat, confidences = _flatten_0171_answers(answers_attr)
        latency_obj = getattr(raw, "latency", None)
        latency_ms = 0.0
        if latency_obj is not None:
            try:
                latency_ms = float(getattr(latency_obj, "total_ms", 0.0) or 0.0)
            except (TypeError, ValueError):
                latency_ms = 0.0
        meta = getattr(raw, "meta", None) or {}
        hard_fail = bool(meta.get("hard_fail")) if isinstance(meta, dict) else False
        ok = bool(flat) and not hard_fail
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return DecisionResult(
            ok=ok,
            answers=flat,
            provider=str(getattr(raw, "provider", None) or "decision"),
            latency_ms=latency_ms,
            error="" if ok else "decision returned no answers",
            confidence=confidence,
            source=str(getattr(raw, "source", None) or "app.decision"),
        )

    return DecisionResult(
        ok=False,
        source="app.decision",
        error=f"Unexpected decide() return type: {type(raw).__name__}",
    )


def _ops_targets_from_questions(
    questions: list[DecisionQuestion],
) -> tuple[list[str], list[str]]:
    ops: list[str] = []
    targets: list[str] = []
    for q in questions:
        if q.id in {"operation", "op"}:
            ops = [str(o) for o in q.options if str(o).strip()]
        elif q.id in {"target_id", "target"}:
            targets = [str(t) for t in q.options if str(t).strip()]
    return ops, targets


def _goal_and_frame_from_state(state: dict[str, Any]) -> tuple[str, str, str, str]:
    goal = str(state.get("goal") or state.get("user_message") or "").strip()
    suggested_op = str(state.get("suggested_operation") or "").strip()
    suggested_tid = str(state.get("suggested_target_id") or "").strip()
    frame_id = str(state.get("frame_id") or "").strip()
    frame = state.get("frame")
    if isinstance(frame, dict):
        if not frame_id:
            frame_id = str(frame.get("frame_id") or "").strip()
        if not suggested_op:
            suggested_op = str(frame.get("suggested_operation") or "").strip()
        if not suggested_tid:
            suggested_tid = str(frame.get("suggested_target_id") or "").strip()
    return goal, suggested_op, suggested_tid, frame_id


class FailClosedDecideClient:
    """Honest refuse when RFC-0171 Reflex Lane is not wired on this tip."""

    def decide(
        self,
        state: dict[str, Any],
        questions: list[DecisionQuestion],
        decision_class: str | DecisionClass,
        *,
        deadline_ms: int = 100,
        privacy: str = "local_only",
    ) -> DecisionResult:
        del state, questions, deadline_ms, privacy
        klass = map_decision_class(decision_class)
        return DecisionResult(
            ok=False,
            provider="none",
            source="fail_closed_stub",
            error=(
                f"RFC-0171 Reflex Lane decide() is not available for class={klass}. "
                "Refuse closed — no fabricated operation/target."
            ),
        )


class DecisionPackageForwarder:
    """Forward to ``app.decision`` surfaces / decide with 0171 contracts."""

    def __init__(
        self,
        decide_fn: Any | None = None,
        browser_op_target_fn: Any | None = None,
    ) -> None:
        self._decide = decide_fn
        self._browser_op_target = browser_op_target_fn

    def decide(
        self,
        state: dict[str, Any],
        questions: list[DecisionQuestion],
        decision_class: str | DecisionClass,
        *,
        deadline_ms: int = 100,
        privacy: str = "local_only",
    ) -> DecisionResult:
        klass = map_decision_class(decision_class)
        privacy_mode = map_privacy(privacy)
        state = state or {}

        if klass == BROWSER_OP_TARGET_CLASS and callable(self._browser_op_target):
            ops, targets = _ops_targets_from_questions(questions)
            goal, suggested_op, suggested_tid, frame_id = _goal_and_frame_from_state(state)
            try:
                raw = self._browser_op_target(
                    goal=goal,
                    operations=ops,
                    target_ids=targets,
                    suggested_operation=suggested_op,
                    suggested_target_id=suggested_tid,
                    frame_id=frame_id,
                    deadline_ms=float(deadline_ms),
                    privacy=privacy_mode,
                )
            except Exception as exc:
                log.warning("browser_operation_target surface failed: %s", exc)
                return DecisionResult(
                    ok=False,
                    source="app.decision.surfaces",
                    error=f"browser_operation_target failed: {exc}",
                )
            return adapt_decision_result(raw)

        if not callable(self._decide):
            return DecisionResult(
                ok=False,
                source="app.decision",
                error=f"No decide() available for class={klass}",
            )

        payload = questions_to_0171_map(questions)
        try:
            raw = self._decide(
                state,
                payload,
                klass,
                float(deadline_ms),
                privacy_mode,
            )
        except TypeError:
            # Keyword-tolerant path for alternate signatures.
            try:
                raw = self._decide(
                    state,
                    payload,
                    klass,
                    deadline_ms=float(deadline_ms),
                    privacy=privacy_mode,
                )
            except Exception as exc:
                log.warning("app.decision.decide failed: %s", exc)
                return DecisionResult(
                    ok=False,
                    source="app.decision",
                    error=f"decide() failed: {exc}",
                )
        except Exception as exc:
            log.warning("app.decision.decide failed: %s", exc)
            return DecisionResult(
                ok=False,
                source="app.decision",
                error=f"decide() failed: {exc}",
            )
        return adapt_decision_result(raw)


def _try_import_decision_api() -> tuple[Any | None, Any | None]:
    """Return ``(decide_fn, browser_operation_target_fn)`` when app.decision imports."""
    try:
        mod = importlib.import_module("app.decision")
    except Exception:
        return None, None

    decide_fn = getattr(mod, "decide", None)
    surface_fn = getattr(mod, "browser_operation_target", None)

    if not callable(surface_fn):
        try:
            surfaces = importlib.import_module("app.decision.surfaces")
            surface_fn = getattr(surfaces, "browser_operation_target", None)
        except Exception:
            surface_fn = None

    if not callable(decide_fn):
        for sub in ("reflex", "api", "lane"):
            try:
                submod = importlib.import_module(f"app.decision.{sub}")
            except Exception:
                continue
            decide_fn = getattr(submod, "decide", None)
            if callable(decide_fn):
                break
        else:
            decide_fn = None

    return (
        decide_fn if callable(decide_fn) else None,
        surface_fn if callable(surface_fn) else None,
    )


_CLIENT: ReflexDecideClient | None = None


def get_reflex_decide_client(*, force_reload: bool = False) -> ReflexDecideClient:
    """Return the live 0171 client when present, else fail-closed stub."""
    global _CLIENT
    if _CLIENT is not None and not force_reload:
        return _CLIENT
    decide_fn, surface_fn = _try_import_decision_api()
    if decide_fn is not None or surface_fn is not None:
        log.info(
            "RFC-0172 using app.decision%s for Reflex Lane",
            " surfaces.browser_operation_target" if surface_fn else " decide()",
        )
        _CLIENT = DecisionPackageForwarder(
            decide_fn=decide_fn,
            browser_op_target_fn=surface_fn,
        )
    else:
        log.info("RFC-0172 Reflex Lane unavailable — fail-closed decide stub active")
        _CLIENT = FailClosedDecideClient()
    return _CLIENT


def set_reflex_decide_client(client: ReflexDecideClient | None) -> None:
    """Test/injection hook. Pass None to clear and re-resolve on next get."""
    global _CLIENT
    _CLIENT = client
