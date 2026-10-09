"""Provider-neutral System-One Reflex API (RFC-0171).

decide(state, questions, decision_class, deadline_ms, privacy)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from uuid import uuid4

from . import audit, cache, metrics, quartermaster
from .adapters import generative, jev_adapter, laya_adapter, rules
from .laya import runtime as laya_runtime
from .policy import approval_popup_required
from .types import (
    POLICY_HARDENED_CLASSES,
    REFLEX_DECISION_CLASSES,
    Answer,
    DecisionResult,
    LatencyBreakdown,
    PrivacyMode,
    ProviderName,
    Question,
    compact_state,
    normalize_questions,
)

log = logging.getLogger("jarvis.decision.reflex")

DEFAULT_DEADLINE_MS = 100.0
_ADAPTERS = {
    "rules": rules,
    "laya": laya_adapter,
    "jev": jev_adapter,
    "generative": generative,
}


def _bounded_answer(question: Question, answer: Answer | None) -> Answer | None:
    """Return the answer only if it stays inside the question's typed domain."""
    if answer is None:
        return None
    value = answer.value
    if question.type == "choice":
        if not isinstance(value, str) or value not in question.choices:
            return None
        return answer
    if question.type == "score":
        if isinstance(value, bool):
            return None
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        if score != score or not question.min_score <= score <= question.max_score:
            return None
        return Answer(question.id, "score", score, answer.confidence)
    if question.type == "boolean":
        if isinstance(value, bool):
            return answer
        return None
    if isinstance(value, bool):
        return None
    try:
        noul = float(value)
    except (TypeError, ValueError):
        return None
    if noul != noul or not 0.0 <= noul <= 1.0:
        return None
    return Answer(question.id, "noul", noul, answer.confidence)


def _enforce_bounds(result: DecisionResult, questions: list[Question]) -> list[str]:
    """Drop out-of-domain provider answers in place; return ids that are now missing."""
    missing: list[str] = []
    bounded: dict[str, Answer] = {}
    for question in questions:
        answer = _bounded_answer(question, result.answers.get(question.id))
        if answer is None:
            missing.append(question.id)
        else:
            bounded[question.id] = answer
    result.answers = bounded
    return missing


def _quality(result: DecisionResult) -> float:
    if not result.answers:
        return 0.0
    confs = [a.confidence for a in result.answers.values() if a.confidence is not None]
    if not confs:
        return 0.6 if not result.fallback_used else 0.35
    return sum(confs) / len(confs)


def _apply_policy_guard(
    *,
    state: dict[str, Any],
    decision_class: str,
    result: DecisionResult,
) -> DecisionResult:
    """Hard policy/approval cannot be weakened by Jev/Laya."""
    if decision_class not in POLICY_HARDENED_CLASSES and "approval_needed" not in result.answers:
        return result
    policy_deny = bool(state.get("policy_deny"))
    policy_requires = bool(state.get("policy_requires_approval"))
    answer = result.answers.get("approval_needed")
    if answer is None:
        return result
    if answer.type == "boolean":
        jev_noul = 1.0 if bool(answer.value) else 0.0
    else:
        try:
            jev_noul = float(answer.value)
        except (TypeError, ValueError):
            jev_noul = None
    needed = approval_popup_required(
        policy_requires=policy_requires,
        policy_deny=policy_deny,
        jev_noul=jev_noul,
        confidence=answer.confidence,
    )
    if policy_deny:
        forced = False if answer.type == "boolean" else 0.0
        result.answers["approval_needed"] = Answer(
            "approval_needed",
            answer.type,
            forced,
            1.0,
        )
        result.hard_rule = True
        result.meta["policy_guard"] = "deny_wins"
        return result
    if policy_requires and not needed:
        # Must not skip required popup.
        forced = True if answer.type == "boolean" else 1.0
        result.answers["approval_needed"] = Answer(
            "approval_needed",
            answer.type,
            forced,
            1.0,
        )
        result.hard_rule = True
        result.meta["policy_guard"] = "required_popup_preserved"
        return result
    if answer.type == "boolean":
        result.answers["approval_needed"] = Answer(
            "approval_needed",
            "boolean",
            bool(needed),
            answer.confidence,
        )
    else:
        result.answers["approval_needed"] = Answer(
            "approval_needed",
            answer.type,
            1.0 if needed else 0.0,
            answer.confidence,
        )
    return result


def _deadline_fallback(
    *,
    state: dict[str, Any],
    questions: list[Question],
    decision_class: str,
    reason: str,
    request_id: str,
    spent_ms: float,
) -> DecisionResult:
    base = rules.decide(
        state=state,
        questions=questions,
        decision_class=decision_class,
        deadline_ms=50.0,
    )
    result = DecisionResult(
        answers=base.answers,
        source="deadline_fallback",
        decision_class=decision_class,
        provider="rules",
        provider_version=base.provider_version,
        model=base.model,
        fallback_used=True,
        fallback_reason=reason,
        fallback_source="rules",
        latency=LatencyBreakdown(total_ms=spent_ms, inference_ms=base.latency.inference_ms),
        hard_rule=base.hard_rule,
        request_id=request_id,
        meta={"deadline_fallback": True},
    )
    return _apply_policy_guard(state=state, decision_class=decision_class, result=result)


def decide(
    state: dict[str, Any] | None,
    questions: dict[str, Any] | list[Question],
    decision_class: str,
    deadline_ms: float | None = None,
    privacy: PrivacyMode = "local_only",
    *,
    use_cache: bool = True,
    request_id: str | None = None,
) -> DecisionResult:
    """
    Provider-neutral Reflex entrypoint.

    Laya answers bounded decisions first when it is warm. Low confidence hands
    the question to Jev (if allowed) then the generative/model lane. Deterministic
    rules run only for hard safety (policy deny/approval, technical-speak fence).
    """
    started = time.perf_counter()
    raw_state = dict(state or {})
    owner_request_id = raw_state.pop("_owner_turn_request_id", None)
    rid = request_id or owner_request_id or uuid4().hex
    deadline = float(deadline_ms if deadline_ms is not None else DEFAULT_DEADLINE_MS)
    if deadline <= 0:
        deadline = DEFAULT_DEADLINE_MS
    dclass = str(decision_class or "").strip()
    if not dclass:
        raise ValueError("decision_class is required")
    if dclass not in REFLEX_DECISION_CLASSES:
        log.warning("Reflex decide() called with unlisted decision_class %r", dclass)
    qlist = normalize_questions(questions)
    projection = compact_state(raw_state)

    # Hard safety only: policy deny/approval and the technical-speak fence.
    rules_result = rules.decide(
        state=projection,
        questions=qlist,
        decision_class=dclass,
        deadline_ms=min(deadline, 50.0),
    )
    rules_result.request_id = rid
    speak_fence = dclass == "speak_class" and any(
        a.value == "technical" and a.confidence is not None and a.confidence >= 0.85
        for a in rules_result.answers.values()
    )
    # Hard short-circuit is for policy deny and hardened classes only.
    # policy_requires_approval must still reach Jev/Laya; _apply_policy_guard
    # raises the approval floor after the typed provider answers (RFC-0116).
    hard_safety = dclass in POLICY_HARDENED_CLASSES or bool(projection.get("policy_deny"))
    harm_fence = dclass == "harm_veto" and rules_result.hard_rule
    if rules_result.hard_rule and (hard_safety or speak_fence or harm_fence):
        guarded = _apply_policy_guard(state=projection, decision_class=dclass, result=rules_result)
        metrics.record(guarded)
        audit.record_event("reflex_decision", guarded.as_dict())
        quartermaster.record_outcome(dclass, "rules", latency_ms=guarded.latency.total_ms, quality=_quality(guarded))
        return guarded

    laya_ready = laya_runtime.is_ready()
    # Jev is only a candidate here. Check its entitlement/key/WAN gate when
    # actually trying it, after a warm Laya result has had the first chance.
    jev_ready = privacy == "allow_cloud"
    order = quartermaster.select_provider_order(
        dclass,
        privacy=privacy,
        laya_ready=laya_ready,
        jev_ready=jev_ready,
    )

    last_error = ""
    for provider in order:
        remaining = deadline - (time.perf_counter() - started) * 1000.0
        if remaining <= 1.0:
            result = _deadline_fallback(
                state=projection,
                questions=qlist,
                decision_class=dclass,
                reason=f"deadline exceeded before {provider}",
                request_id=rid,
                spent_ms=(time.perf_counter() - started) * 1000.0,
            )
            metrics.record(result)
            audit.record_event("reflex_deadline_fallback", result.as_dict())
            return result

        if provider == "rules":
            continue

        adapter = _ADAPTERS.get(provider)
        if adapter is None:
            continue
        ok, reason = adapter.available(privacy=privacy, decision_class=dclass)
        if not ok:
            last_error = reason
            continue

        if use_cache:
            version = getattr(adapter, "VERSION", provider)
            key = cache.cache_key(
                provider=provider,
                provider_version=str(version),
                decision_class=dclass,
                state=projection,
                questions=qlist,
            )
            cached = cache.get(key)
            if cached:
                cached.request_id = rid
                metrics.record(cached)
                audit.record_event("reflex_cache_hit", cached.as_dict())
                return cached

        try:
            result = adapter.decide(
                state=projection,
                questions=qlist,
                decision_class=dclass,
                deadline_ms=remaining,
            )
        except TimeoutError as exc:
            quartermaster.record_outcome(
                dclass,
                provider,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                quality=0.0,
            )
            result = _deadline_fallback(
                state=projection,
                questions=qlist,
                decision_class=dclass,
                reason=str(exc),
                request_id=rid,
                spent_ms=(time.perf_counter() - started) * 1000.0,
            )
            metrics.record(result)
            audit.record_event("reflex_deadline_fallback", result.as_dict())
            return result
        except Exception as exc:  # noqa: BLE001 — must never strand the turn
            last_error = str(exc)
            quartermaster.record_outcome(
                dclass,
                provider,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                quality=0.0,
            )
            audit.record_event(
                "reflex_provider_error",
                {
                    "provider": provider,
                    "decision_class": dclass,
                    "error": last_error[:400],
                    "fallback_used": True,
                    "request_id": rid,
                },
            )
            continue

        result.request_id = rid
        result.latency.total_ms = (time.perf_counter() - started) * 1000.0
        missing = _enforce_bounds(result, qlist)
        if missing:
            last_error = f"{provider} returned out-of-domain or missing answers for: {', '.join(missing)}"
            quartermaster.record_outcome(dclass, provider, latency_ms=result.latency.total_ms, quality=0.0)
            audit.record_event(
                "reflex_provider_error",
                {
                    "provider": provider,
                    "decision_class": dclass,
                    "error": last_error[:400],
                    "fallback_used": True,
                    "request_id": rid,
                },
            )
            continue
        if result.latency.total_ms > deadline:
            quartermaster.record_outcome(dclass, provider, latency_ms=result.latency.total_ms, quality=0.0)
            result = _deadline_fallback(
                state=projection,
                questions=qlist,
                decision_class=dclass,
                reason=f"{provider} total latency exceeded deadline",
                request_id=rid,
                spent_ms=result.latency.total_ms,
            )
            metrics.record(result)
            audit.record_event("reflex_deadline_fallback", result.as_dict())
            return result

        # Confidence gate: if Laya/Jev confidence is very low, fall through.
        quality = _quality(result)
        if provider in {"laya", "jev"} and quality < 0.35:
            last_error = f"{provider} confidence too low ({quality:.2f})"
            quartermaster.record_outcome(dclass, provider, latency_ms=result.latency.total_ms, quality=quality)
            continue

        # Complexity: rules set a floor — typed providers may raise, never lower.
        if dclass == "complexity_escalation":
            floor = rules_result.answers.get("complexity_tier")
            raised = result.answers.get("complexity_tier")
            if floor and raised and floor.type == "score" and raised.type == "score":
                try:
                    result.answers["complexity_tier"] = Answer(
                        "complexity_tier",
                        "score",
                        max(float(floor.value), float(raised.value)),
                        raised.confidence if raised.confidence is not None else floor.confidence,
                    )
                except (TypeError, ValueError):
                    result.answers["complexity_tier"] = floor

        guarded = _apply_policy_guard(state=projection, decision_class=dclass, result=result)
        if use_cache:
            cache.put(
                cache.cache_key(
                    provider=guarded.provider,
                    provider_version=guarded.provider_version,
                    decision_class=dclass,
                    state=projection,
                    questions=qlist,
                ),
                guarded,
            )
        metrics.record(guarded)
        audit.record_event("reflex_decision", guarded.as_dict())
        quartermaster.record_outcome(
            dclass,
            guarded.provider,
            latency_ms=guarded.latency.total_ms,
            quality=_quality(guarded),
        )
        return guarded

    # Exhausted providers → generative, then rules deadline fallback.
    remaining = deadline - (time.perf_counter() - started) * 1000.0
    if remaining > 1.0:
        try:
            gen = generative.decide(
                state=projection,
                questions=qlist,
                decision_class=dclass,
                deadline_ms=remaining,
            )
            gen.request_id = rid
            gen.fallback_reason = gen.fallback_reason or last_error or "no typed provider"
            gen.fallback_source = "generative"
            gen.latency.total_ms = (time.perf_counter() - started) * 1000.0
            guarded = _apply_policy_guard(state=projection, decision_class=dclass, result=gen)
            metrics.record(guarded)
            audit.record_event("reflex_decision", guarded.as_dict())
            return guarded
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

    result = _deadline_fallback(
        state=projection,
        questions=qlist,
        decision_class=dclass,
        reason=last_error or "all providers failed",
        request_id=rid,
        spent_ms=(time.perf_counter() - started) * 1000.0,
    )
    metrics.record(result)
    audit.record_event("reflex_deadline_fallback", result.as_dict())
    return result


def decide_many(
    jobs: list[dict[str, Any]],
    *,
    max_workers: int = 4,
) -> list[DecisionResult]:
    """Run independent Reflex decisions concurrently (different states)."""
    if not jobs:
        return []
    if len(jobs) == 1:
        job = jobs[0]
        return [
            decide(
                job.get("state"),
                job["questions"],
                job["decision_class"],
                job.get("deadline_ms"),
                job.get("privacy", "local_only"),
            )
        ]

    # Jobs sharing state + class + privacy merge into one decide() call, provided their
    # question ids do not collide with different definitions.
    by_state: dict[str, list[int]] = {}
    for idx, job in enumerate(jobs):
        blob = json.dumps(
            {
                "decision_class": job.get("decision_class"),
                "privacy": job.get("privacy", "local_only"),
                "state": compact_state(job.get("state")),
            },
            sort_keys=True,
            default=str,
        )
        group_key = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        by_state.setdefault(group_key, []).append(idx)

    units: list[tuple[list[int], list[Question]]] = []
    for indexes in by_state.values():
        merged: dict[str, Question] = {}
        conflict = False
        for idx in indexes:
            for question in normalize_questions(jobs[idx]["questions"]):
                prior = merged.get(question.id)
                if prior is not None and prior != question:
                    conflict = True
                    break
                merged[question.id] = question
            if conflict:
                break
        if conflict or len(indexes) == 1:
            units.extend(([idx], normalize_questions(jobs[idx]["questions"])) for idx in indexes)
        else:
            units.append((indexes, list(merged.values())))

    def _run(unit: tuple[list[int], list[Question]]) -> tuple[list[int], DecisionResult]:
        indexes, unit_questions = unit
        job = jobs[indexes[0]]
        return indexes, decide(
            job.get("state"),
            unit_questions,
            job["decision_class"],
            job.get("deadline_ms"),
            job.get("privacy", "local_only"),
        )

    results: list[DecisionResult | None] = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(units)))) as pool:
        for fut in as_completed([pool.submit(_run, unit) for unit in units]):
            indexes, batched = fut.result()
            if len(indexes) == 1:
                results[indexes[0]] = batched
                continue
            for idx in indexes:
                wanted = {q.id for q in normalize_questions(jobs[idx]["questions"])}
                results[idx] = DecisionResult(
                    answers={qid: ans for qid, ans in batched.answers.items() if qid in wanted},
                    source=batched.source,
                    decision_class=batched.decision_class,
                    provider=batched.provider,
                    provider_version=batched.provider_version,
                    model=batched.model,
                    fallback_used=batched.fallback_used,
                    fallback_reason=batched.fallback_reason,
                    fallback_source=batched.fallback_source,
                    cached=batched.cached,
                    latency=batched.latency,
                    hard_rule=batched.hard_rule,
                    request_id=batched.request_id,
                    fixture=batched.fixture,
                    meta={**batched.meta, "batched": True},
                )

    return [r if r is not None else _deadline_fallback(
        state={},
        questions=normalize_questions(jobs[i]["questions"]),
        decision_class=str(jobs[i].get("decision_class") or "turn_batch"),
        reason="missing result",
        request_id=uuid4().hex,
        spent_ms=0.0,
    ) for i, r in enumerate(results)]
