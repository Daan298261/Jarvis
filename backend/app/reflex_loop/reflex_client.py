"""Thin typed client for the RFC-0171 Reflex Lane decide() contract.

Does not reimplement Jev/Laya. When ``app.decision`` exposes the provider-neutral
API, this module forwards to it. Otherwise callers get a fail-closed stub that
honestly refuses decisions (tests inject FakeDecideClient).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable
import importlib
import logging

log = logging.getLogger("jarvis.reflex_loop.client")

# Decision class used for browser/computer operation + target selection (RFC-0171).
BROWSER_OP_TARGET_CLASS = "browser_computer_op_target"


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
    """Typed question for the Reflex Lane (choice / score / boolean)."""

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
        privacy: str = "local",
    ) -> DecisionResult: ...


class FailClosedDecideClient:
    """Honest refuse when RFC-0171 Reflex Lane is not wired on this tip."""

    def decide(
        self,
        state: dict[str, Any],
        questions: list[DecisionQuestion],
        decision_class: str | DecisionClass,
        *,
        deadline_ms: int = 100,
        privacy: str = "local",
    ) -> DecisionResult:
        del state, questions, deadline_ms, privacy
        klass = (
            decision_class.value
            if isinstance(decision_class, DecisionClass)
            else str(decision_class)
        )
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
    """Forward to ``app.decision.decide`` when D1 lands the 0171 API."""

    def __init__(self, decide_fn: Any) -> None:
        self._decide = decide_fn

    def decide(
        self,
        state: dict[str, Any],
        questions: list[DecisionQuestion],
        decision_class: str | DecisionClass,
        *,
        deadline_ms: int = 100,
        privacy: str = "local",
    ) -> DecisionResult:
        klass = (
            decision_class.value
            if isinstance(decision_class, DecisionClass)
            else str(decision_class)
        )
        payload = [
            {
                "id": q.id,
                "kind": q.kind,
                "prompt": q.prompt,
                "options": list(q.options),
                "min_score": q.min_score,
                "max_score": q.max_score,
            }
            for q in questions
        ]
        raw = self._decide(
            state,
            payload,
            klass,
            deadline_ms=deadline_ms,
            privacy=privacy,
        )
        if isinstance(raw, DecisionResult):
            return raw
        if isinstance(raw, dict):
            return DecisionResult(
                ok=bool(raw.get("ok", True)),
                answers=dict(raw.get("answers") or {}),
                provider=str(raw.get("provider") or "decision"),
                latency_ms=float(raw.get("latency_ms") or 0.0),
                error=str(raw.get("error") or ""),
                confidence=float(raw.get("confidence") or 0.0),
                source=str(raw.get("source") or "app.decision"),
            )
        return DecisionResult(
            ok=False,
            source="app.decision",
            error=f"Unexpected decide() return type: {type(raw).__name__}",
        )


def _try_import_decision_decide() -> Any | None:
    try:
        mod = importlib.import_module("app.decision")
    except Exception:
        return None
    decide_fn = getattr(mod, "decide", None)
    if callable(decide_fn):
        return decide_fn
    # Nested package shapes D1 may land: app.decision.reflex / api
    for sub in ("reflex", "api", "lane"):
        try:
            submod = importlib.import_module(f"app.decision.{sub}")
        except Exception:
            continue
        decide_fn = getattr(submod, "decide", None)
        if callable(decide_fn):
            return decide_fn
    return None


_CLIENT: ReflexDecideClient | None = None


def get_reflex_decide_client(*, force_reload: bool = False) -> ReflexDecideClient:
    """Return the live 0171 client when present, else fail-closed stub."""
    global _CLIENT
    if _CLIENT is not None and not force_reload:
        return _CLIENT
    decide_fn = _try_import_decision_decide()
    if decide_fn is not None:
        log.info("RFC-0172 using app.decision decide() for Reflex Lane")
        _CLIENT = DecisionPackageForwarder(decide_fn)
    else:
        log.info("RFC-0172 Reflex Lane unavailable — fail-closed decide stub active")
        _CLIENT = FailClosedDecideClient()
    return _CLIENT


def set_reflex_decide_client(client: ReflexDecideClient | None) -> None:
    """Test/injection hook. Pass None to clear and re-resolve on next get."""
    global _CLIENT
    _CLIENT = client
