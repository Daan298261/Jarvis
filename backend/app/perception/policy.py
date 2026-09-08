from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import SocialPerceptionSettings
from .models import ObservationCandidate, PolicyResult, StructuredObservation
from .store import PerceptionStateStore


@dataclass(frozen=True)
class _Fact:
    key: str
    value: str | bool | int
    category: str
    priority: str
    confidence: float


_PRIORITY_RANK = {"casual": 1, "social": 2, "practical": 3}


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed_seconds(now: datetime, then_raw: str | None) -> float | None:
    then = _parse_time(then_raw)
    if then is None:
        return None
    return max(0.0, (now - then).total_seconds())


def _value_token(value: str | bool | int) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _object_key(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:48]
    return f"object.{slug or 'visible_object'}"


class PerceptionPolicy:
    """Turn safe structured observations into sparse, deterministic candidate events."""

    def __init__(self, settings: SocialPerceptionSettings, store: PerceptionStateStore) -> None:
        self.settings = settings
        self.store = store

    def evaluate(self, observation: StructuredObservation) -> PolicyResult:
        if not self.settings.enabled:
            return PolicyResult(accepted=False, reason="disabled", candidates=[], evaluated_facts=0)

        facts = self._flatten(observation)
        now = observation.observed_at
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        now_iso = _utc_iso(now)

        def apply(state: dict[str, Any]) -> PolicyResult:
            fact_state: dict[str, Any] = state.setdefault("facts", {})
            baseline: dict[str, Any] = state.setdefault("baseline", {})
            proposed: list[tuple[int, ObservationCandidate]] = []

            for fact in facts:
                if fact.confidence < self.settings.min_confidence:
                    continue

                previous = fact_state.get(fact.key)
                first_seen = previous is None
                changed = previous is not None and previous.get("value") != fact.value
                duplicate = previous is not None and previous.get("value") == fact.value

                baseline_novelty = self._baseline_novelty(baseline.get(fact.key), fact.value)
                novelty = 1.0 if first_seen else (max(0.60, baseline_novelty) if changed else 0.0)

                if previous is None:
                    previous = {
                        "value": fact.value,
                        "first_seen": now_iso,
                        "last_seen": now_iso,
                        "count": 0,
                        "last_confidence": fact.confidence,
                        "last_emitted_at": None,
                        "last_emitted_value": None,
                    }
                    fact_state[fact.key] = previous

                previous["value"] = fact.value
                previous["last_seen"] = now_iso
                previous["count"] = int(previous.get("count", 0)) + 1
                previous["last_confidence"] = fact.confidence

                if self.settings.baseline_enabled:
                    self._update_baseline(baseline, fact)

                if duplicate or novelty < self.settings.novelty_threshold:
                    continue

                # Duplicate TTL applies to re-emitting the same value, not to a real
                # state transition (e.g. tidy -> dishevelled).
                since_fact_emit = _elapsed_seconds(now, previous.get("last_emitted_at"))
                if (
                    since_fact_emit is not None
                    and since_fact_emit < self.settings.duplicate_ttl_seconds
                    and previous.get("last_emitted_value") == fact.value
                ):
                    continue

                reason = "first_seen" if first_seen else "changed_value"
                candidate = ObservationCandidate(
                    category=fact.category,
                    fact=fact.key,
                    value=fact.value,
                    confidence=fact.confidence,
                    novelty=novelty,
                    priority=fact.priority,
                    safe_to_comment=True,
                    reason=reason,
                    observed_at=now,
                )
                proposed.append((_PRIORITY_RANK[fact.priority], candidate))

            state["last_observation_at"] = now_iso

            if not proposed:
                return PolicyResult(
                    accepted=True,
                    reason="no_candidate",
                    candidates=[],
                    evaluated_facts=len(facts),
                )

            since_global = _elapsed_seconds(now, state.get("last_candidate_at"))
            if since_global is not None and since_global < self.settings.comment_cooldown_seconds:
                return PolicyResult(
                    accepted=True,
                    reason="global_cooldown",
                    candidates=[],
                    evaluated_facts=len(facts),
                )

            # One spontaneous candidate per observation keeps the downstream dialogue
            # queue sparse. Practical changes outrank social, which outrank casual.
            proposed.sort(key=lambda item: (item[0], item[1].novelty, item[1].confidence), reverse=True)
            candidate = proposed[0][1]
            fact_state[candidate.fact]["last_emitted_at"] = now_iso
            fact_state[candidate.fact]["last_emitted_value"] = candidate.value
            state["last_candidate_at"] = now_iso
            return PolicyResult(
                accepted=True,
                reason="candidate",
                candidates=[candidate],
                evaluated_facts=len(facts),
            )

        return self.store.mutate(apply)

    def _flatten(self, observation: StructuredObservation) -> list[_Fact]:
        facts: list[_Fact] = []

        def confidence(key: str, *aliases: str) -> float:
            for lookup in (key, *aliases):
                if lookup in observation.attributes:
                    return float(observation.attributes[lookup])
            return observation.confidence

        if observation.person_present is not None:
            facts.append(_Fact(
                "person.present",
                observation.person_present,
                "presence",
                "social",
                confidence("person.present"),
            ))
        if observation.person_count is not None:
            facts.append(_Fact(
                "person.count",
                observation.person_count,
                "presence",
                "social",
                confidence("person.count"),
            ))
        if observation.environment and observation.environment.lighting is not None:
            facts.append(_Fact(
                "environment.lighting",
                observation.environment.lighting,
                "environment",
                "practical",
                confidence("environment.lighting", "lighting"),
            ))
        if observation.activity is not None:
            facts.append(_Fact(
                "activity",
                observation.activity,
                "activity",
                "practical",
                confidence("activity"),
            ))
        for label in observation.objects:
            key = _object_key(label)
            facts.append(_Fact(key, True, "object", "practical", confidence(key)))
        if observation.appearance:
            if observation.appearance.hair_state is not None:
                facts.append(_Fact(
                    "appearance.hair_state",
                    observation.appearance.hair_state,
                    "appearance",
                    "casual",
                    confidence("appearance.hair_state", "hair_state"),
                ))
            if observation.appearance.glasses is not None:
                facts.append(_Fact(
                    "appearance.glasses",
                    observation.appearance.glasses,
                    "appearance",
                    "casual",
                    confidence("appearance.glasses", "glasses"),
                ))
            if observation.appearance.clothing_summary is not None:
                facts.append(_Fact(
                    "appearance.clothing_summary",
                    observation.appearance.clothing_summary,
                    "appearance",
                    "casual",
                    confidence("appearance.clothing_summary", "clothing_summary"),
                ))
        return facts

    @staticmethod
    def _baseline_novelty(record: dict[str, Any] | None, value: str | bool | int) -> float:
        if not record:
            return 1.0
        total = int(record.get("total", 0))
        if total <= 0:
            return 1.0
        count = int((record.get("values") or {}).get(_value_token(value), 0))
        return max(0.0, min(1.0, 1.0 - (count / total)))

    @staticmethod
    def _update_baseline(baseline: dict[str, Any], fact: _Fact) -> None:
        record = baseline.setdefault(fact.key, {"total": 0, "values": {}})
        record["total"] = int(record.get("total", 0)) + 1
        values = record.setdefault("values", {})
        token = _value_token(fact.value)
        values[token] = int(values.get(token, 0)) + 1
