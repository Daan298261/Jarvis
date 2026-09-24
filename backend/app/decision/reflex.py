"""Provider-neutral System-One Reflex Lane API (RFC-0171).

decide(state, questions, decision_class, deadline_ms, privacy)
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any, Iterable, Sequence

from . import audit, cache, metrics
from .adapters.generative import ADAPTER as GENERATIVE_ADAPTER
from .adapters.jev_adapter import ADAPTER as JEV_ADAPTER
from .adapters.laya_adapter import ADAPTER as LAYA_ADAPTER
from .adapters.rules import ADAPTER as RULES_ADAPTER
from .laya import ready as laya_ready
from .provider_select import select_provider_order
from .tier import jev_calls_allowed, resolve_status
from .types import (
    Answer,
    DecideRequest,
    DecisionResult,
    DecisionSource,
    LatencyBreakdown,
    PrivacyMode,
    Question,
)

_ADAPTERS = {
    "rules": RULES_ADAPTER,
    "laya": LAYA_ADAPTER,
    "jev": JEV_ADAPTER,
    "generative_fallback": GENERATIVE_ADAPTER,
}

# Rules answers at or above this confidence are hard locks (policy/invariants).
_HARD_RULE_CONFIDENCE = 0.95


def _normalize_questions(questions: Sequence[Question] | Iterable[Question]) -> tuple[Question, ...]:
    items = tuple(questions)
    if not items:
        raise ValueError("decide() requires at least one typed question")
    seen: set[str] = set()
    for q in items:
        if not q.id or q.id in seen:
            raise ValueError(f"duplicate or empty question id: {q.id!r}")
        seen.add(q.id)
        if q.type == "choice" and not q.choices:
            raise ValueError(f"choice question {q.id!r} requires choices")
    return items


def _cloud_allowed() -> bool:
    allowed, _reason = jev_calls_allowed(resolve_status())
    return allowed


def _complete(answers: dict[str, Answer], questions: tuple[Question, ...]) -> bool:
    return all(q.id in answers for q in questions)


def _split_hard_soft(answers: dict[str, Answer]) -> tuple[dict[str, Answer], dict[str, Answer]]:
    hard: dict[str, Answer] = {}
    soft: dict[str, Answer] = {}
    for qid, answer in answers.items():
        conf = answer.confidence if answer.confidence is not None else 0.0
        if conf >= _HARD_RULE_CONFIDENCE:
            hard[qid] = answer
        else:
            soft[qid] = answer
    return hard, soft


def _merge(locked: dict[str, Answer], *layers: dict[str, Answer]) -> dict[str, Answer]:
    merged = dict(locked)
    for layer in layers:
        for qid, answer in layer.items():
            if qid in locked:
                continue
            merged[qid] = answer
    return merged


def decide(
    state: dict[str, Any],
    questions: Sequence[Question] | Iterable[Question],
    decision_class: str,
    deadline_ms: int = 100,
    privacy: PrivacyMode = "local_only",
    *,
    use_cache: bool = True,
) -> DecisionResult:
    """Bounded typed decisions. Hard rules lock first; Laya preferred; Jev opt-in; generative last."""
    started = time.perf_counter()
    qtuple = _normalize_questions(questions)
    dclass = str(decision_class or "generic").strip() or "generic"
    deadline = max(1, int(deadline_ms or 100))
    request = DecideRequest(
        state=dict(state or {}),
        questions=qtuple,
        decision_class=dclass,
        deadline_ms=deadline,
        privacy=privacy,
    )

    order = select_provider_order(
        dclass,
        privacy=privacy,
        cloud_allowed=_cloud_allowed(),
        laya_ready=laya_ready(),
        jev_ready=_cloud_allowed() and privacy == "cloud_ok",
    )

    cache_provider = ",".join(order)
    cache_version = "reflex-v1"
    key = ""
    if use_cache and cache.all_questions_pure(qtuple):
        key = cache.cache_key(
            provider=cache_provider,
            provider_version=cache_version,
            decision_class=dclass,
            state=request.state,
            questions=qtuple,
        )
        cached = cache.get(key)
        if cached is not None and _complete(cached, qtuple):
            result = DecisionResult(
                answers=cached,
                source="cache",
                decision_class=dclass,
                provider="cache",
                provider_version=cache_version,
                fallback_used=False,
                latency=LatencyBreakdown(total_ms=(time.perf_counter() - started) * 1000.0),
                batch_size=len(qtuple),
                cached=True,
            )
            metrics.record(result)
            audit.record_event("reflex_decision", result.to_dict())
            return result

    locked: dict[str, Answer] = {}
    soft_rules: dict[str, Answer] = {}
    answers: dict[str, Answer] = {}
    source: DecisionSource = "rules"
    provider = "rules"
    provider_version = "rules-v1"
    fallback_used = False
    fallback_reason = ""
    deadline_hit = False
    inference_ms = 0.0
    network_ms = 0.0
    system_one_applied = False

    # 1) Deterministic hard rules always run first.
    rules_answers, rules_version, rules_ms = RULES_ADAPTER.decide(request)
    inference_ms += rules_ms
    locked, soft_rules = _split_hard_soft(rules_answers)
    answers = _merge(locked, soft_rules)
    provider_version = rules_version

    # 2) System-One providers for unlocked questions (Laya preferred when ready).
    for name in order:
        if name == "rules":
            continue
        if name == "generative_fallback":
            continue
        if _complete(locked, qtuple):
            break
        remaining_ms = deadline - (time.perf_counter() - started) * 1000.0
        if remaining_ms <= 0:
            deadline_hit = True
            fallback_used = True
            fallback_reason = "hard deadline exceeded"
            break

        adapter = _ADAPTERS[name]
        ok, reason = adapter.available(request)
        if not ok:
            fallback_used = True
            fallback_reason = reason or f"{name} unavailable"
            continue

        missing = tuple(q for q in qtuple if q.id not in locked)
        if not missing:
            break
        sub_request = DecideRequest(
            state=request.state,
            questions=missing,
            decision_class=request.decision_class,
            deadline_ms=int(remaining_ms),
            privacy=request.privacy,
        )

        def _call() -> tuple[dict[str, Answer], str, float]:
            return adapter.decide(sub_request)

        call_started = time.perf_counter()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_call)
                try:
                    got, version, inf_ms = future.result(timeout=max(0.001, remaining_ms / 1000.0))
                except concurrent.futures.TimeoutError:
                    deadline_hit = True
                    fallback_used = True
                    fallback_reason = f"{name} exceeded deadline_ms={deadline}"
                    continue
        except Exception as exc:  # noqa: BLE001 — never strand the turn
            fallback_used = True
            fallback_reason = f"{name} error: {exc}"
            continue

        elapsed = (time.perf_counter() - call_started) * 1000.0
        inference_ms += float(inf_ms or 0.0)
        if name == "jev":
            network_ms += max(0.0, elapsed - float(inf_ms or 0.0))

        answers = _merge(locked, got, soft_rules)
        source = name  # type: ignore[assignment]
        provider = name
        provider_version = version
        system_one_applied = True
        fallback_used = False
        fallback_reason = ""
        if _complete(answers, qtuple):
            break

    # 3) Soft rules fill gaps before generative.
    if not _complete(answers, qtuple):
        answers = _merge(locked, answers, soft_rules)
        if not system_one_applied:
            source = "rules"
            provider = "rules"
            provider_version = rules_version

    # 4) Generative / deadline fallback — explicit + audited; never strands.
    if not _complete(answers, qtuple) or deadline_hit and not _complete(answers, qtuple):
        remaining = tuple(q for q in qtuple if q.id not in answers)
        if remaining:
            sub = DecideRequest(
                state=request.state,
                questions=remaining,
                decision_class=request.decision_class,
                deadline_ms=max(1, int(deadline - (time.perf_counter() - started) * 1000.0)),
                privacy=request.privacy,
            )
            gen_answers, gen_version, gen_ms = GENERATIVE_ADAPTER.decide(sub)
            inference_ms += gen_ms
            answers = _merge(locked, answers, gen_answers)
            source = "deadline_fallback" if deadline_hit else "generative_fallback"
            provider = source
            provider_version = gen_version
            fallback_used = True
            if not fallback_reason:
                fallback_reason = "generative fallback after incomplete System-One coverage"

    if deadline_hit and source not in {"deadline_fallback"}:
        # Deadline hit but earlier provider completed — still audit the miss signal.
        fallback_used = True
        if not fallback_reason:
            fallback_reason = "hard deadline exceeded"

    if not system_one_applied and source == "rules" and _complete(answers, qtuple):
        fallback_used = False
        fallback_reason = ""

    total_ms = (time.perf_counter() - started) * 1000.0
    result = DecisionResult(
        answers=answers,
        source=source,
        decision_class=dclass,
        provider=provider,
        provider_version=provider_version,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        deadline_hit=deadline_hit,
        latency=LatencyBreakdown(
            inference_ms=inference_ms,
            network_ms=network_ms,
            total_ms=total_ms,
        ),
        batch_size=len(qtuple),
        cached=False,
    )

    if (
        use_cache
        and key
        and cache.all_questions_pure(qtuple)
        and not deadline_hit
        and not fallback_used
        and _complete(result.answers, qtuple)
    ):
        cache.put(key, result.answers)

    metrics.record(result)
    audit.record_event(
        "reflex_decision",
        {
            **result.to_dict(),
            "provider_order": list(order),
            "hard_locked": sorted(locked.keys()),
        },
    )
    return result


def decide_many_independent(
    jobs: Sequence[tuple[dict[str, Any], Sequence[Question], str]],
    *,
    deadline_ms: int = 100,
    privacy: PrivacyMode = "local_only",
) -> list[DecisionResult]:
    """Run independent Reflex decisions concurrently (different states)."""
    if not jobs:
        return []

    def _one(job: tuple[dict[str, Any], Sequence[Question], str]) -> DecisionResult:
        state, questions, dclass = job
        return decide(state, questions, dclass, deadline_ms=deadline_ms, privacy=privacy)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        return list(pool.map(_one, jobs))
