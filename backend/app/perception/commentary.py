from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config import (
    PersonalObservations,
    SocialCommentarySettings,
    load_settings,
)
from ..persona.commentary_runtime import CommentaryActivitySnapshot, RUNTIME
from ..persona.social import (
    allowed_appearance_comment,
    effective_sarcasm,
    fact_is_sensitive,
    interruption_class_for,
    resolve_address_style,
    semantic_hash,
    topic_from_candidate,
)
from .commentary_store import CommentaryStateStore, append_recent_record
from .models import ObservationCandidate

CommentTone = Literal["off", "light", "dry", "sharp", "neutral"]
InterruptionClass = Literal["urgent", "practical", "social", "casual"]
CommentImportance = Literal["casual", "social", "practical", "urgent"]

_FREQUENCY_COOLDOWNS_SECONDS: dict[str, tuple[int | None, int | None]] = {
    "silent": (None, None),
    "restrained": (30 * 60, 4 * 3600),
    "normal": (15 * 60, 2 * 3600),
    "talkative": (7 * 60, 3600),
    "butler": (4 * 60, 30 * 60),
}

_MAX_WORDS_BY_FREQUENCY = {
    "silent": 0,
    "restrained": 18,
    "normal": 22,
    "talkative": 26,
    "butler": 28,
}


class CommentaryPresence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_state: Literal["disabled", "unknown", "provisional", "confirmed"] = "disabled"
    relationship: Literal["owner", "household_member", "trusted_person"] | None = None
    person_count: int = Field(default=0, ge=0, le=32)
    unknown_guest_present: bool = False


class CommentIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["social_comment"] = "social_comment"
    topic: str = Field(min_length=1, max_length=96)
    value: str | bool | int
    importance: CommentImportance
    tone: CommentTone
    address_style: str
    max_words: int = Field(ge=1, le=40)
    must_not_repeat_fact_verbatim: bool = False
    interruption_class: InterruptionClass
    context: dict[str, float | int | str | bool] = Field(default_factory=dict)


class CommentaryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["suppress", "intent"]
    reason: str
    intent: CommentIntent | None = None
    candidate_fact: str | None = None


class CommentaryFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["more_like_this", "less_like_this", "dont_comment_topic", "too_sarcastic"]
    topic: str | None = Field(default=None, max_length=96)


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


def _tone_from_sarcasm(sarcasm: str) -> CommentTone:
    if sarcasm == "off":
        return "neutral"
    return sarcasm


def _importance_for(candidate: ObservationCandidate, interruption: InterruptionClass) -> CommentImportance:
    if interruption == "urgent":
        return "urgent"
    if interruption == "practical":
        return "practical"
    if interruption == "social":
        return "social"
    return "casual"


class SocialCommentaryPolicy:
    """Deterministic gate between RFC-0053 candidates and dialogue/TTS."""

    def __init__(
        self,
        settings: SocialCommentarySettings | None = None,
        store: CommentaryStateStore | None = None,
    ) -> None:
        self.settings = settings or load_settings().social_commentary
        self.store = store or CommentaryStateStore()

    def evaluate(
        self,
        candidate: ObservationCandidate,
        *,
        presence: CommentaryPresence | None = None,
        activity: CommentaryActivitySnapshot | None = None,
        now: datetime | None = None,
        structured_counts: dict[str, int] | None = None,
    ) -> CommentaryDecision:
        presence = presence or CommentaryPresence()
        activity = activity or RUNTIME.snapshot()
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)

        fact_key = candidate.fact
        topic = topic_from_candidate(candidate)

        def suppress(reason: str) -> CommentaryDecision:
            self._record_decision(candidate, None, reason, now)
            return CommentaryDecision(outcome="suppress", reason=reason, candidate_fact=fact_key)

        if not self.settings.enabled:
            return suppress("disabled")
        if self.settings.comment_frequency == "silent":
            return suppress("frequency_silent")
        if not candidate.safe_to_comment:
            return suppress("unsafe_candidate")
        if candidate.confidence < self.settings.min_confidence:
            return suppress("low_confidence")
        if candidate.novelty < self.settings.min_novelty:
            return suppress("low_novelty")
        if fact_is_sensitive(candidate):
            return suppress("sensitive_fact")
        if not self._category_allowed(candidate):
            return suppress("category_not_permitted")
        if self._guest_blocks_personal(candidate, presence):
            return suppress("guest_privacy")
        if self.settings.do_not_disturb:
            return suppress("do_not_disturb")
        if self.settings.focus_mode and candidate.priority == "casual":
            return suppress("focus_mode")
        if activity.jarvis_listening_to_user:
            return suppress("jarvis_listening")
        if activity.user_speaking:
            return suppress("user_speaking")
        if activity.jarvis_speaking:
            return suppress("jarvis_speaking")
        if activity.urgent_alert_active and candidate.priority != "practical":
            return suppress("urgent_alert_active")
        if activity.high_priority_tool_active:
            return suppress("high_priority_tool")

        interruption = interruption_class_for(candidate)
        if candidate.category == "appearance" and interruption != "casual":
            interruption = "casual"

        if interruption == "casual" and (
            activity.user_speaking
            or activity.jarvis_speaking
            or activity.high_priority_tool_active
            or activity.urgent_alert_active
        ):
            return suppress("casual_requires_idle")

        if interruption in {"practical", "social", "casual"} and (
            activity.user_speaking or activity.jarvis_speaking
        ):
            return suppress("conversational_gap_required")

        global_cd, topic_cd = _FREQUENCY_COOLDOWNS_SECONDS[self.settings.comment_frequency]
        state = self.store.load()
        if self._topic_suppressed(state, topic, now):
            return suppress("topic_feedback_suppressed")

        since_global = _elapsed_seconds(now, state.get("last_global_comment_at"))
        if global_cd is not None and since_global is not None and since_global < global_cd:
            return suppress("global_cooldown")

        topic_times: dict[str, Any] = state.get("topic_last_comment_at") or {}
        since_topic = _elapsed_seconds(now, topic_times.get(topic))
        if topic_cd is not None and since_topic is not None and since_topic < topic_cd:
            return suppress("topic_cooldown")

        fact_times: dict[str, Any] = state.get("fact_last_comment_at") or {}
        since_fact = _elapsed_seconds(now, fact_times.get(fact_key))
        if topic_cd is not None and since_fact is not None and since_fact < topic_cd:
            return suppress("fact_repetition")

        fact_digest = semantic_hash(f"{fact_key}:{candidate.value}")
        if fact_digest in set(state.get("semantic_hashes") or []):
            return suppress("semantic_repetition")

        sarcasm_penalty = self._sarcasm_penalty_active(state, now)
        tone = _tone_from_sarcasm(effective_sarcasm(self.settings, sarcasm_penalty))
        address = resolve_address_style(self.settings)

        context: dict[str, float | int | str | bool] = {
            "novelty": round(candidate.novelty, 3),
            "confidence": round(candidate.confidence, 3),
        }
        if structured_counts:
            for key, value in structured_counts.items():
                if key in {"repeat_count_today", "elapsed_minutes"}:
                    context[key] = int(value)

        intent = CommentIntent(
            topic=topic,
            value=candidate.value,
            importance=_importance_for(candidate, interruption),
            tone=tone,
            address_style=address,
            max_words=_MAX_WORDS_BY_FREQUENCY[self.settings.comment_frequency],
            must_not_repeat_fact_verbatim=candidate.category == "appearance",
            interruption_class=interruption,
            context=context,
        )

        def commit(state: dict[str, Any]) -> CommentaryDecision:
            now_iso = _utc_iso(now)
            state["last_global_comment_at"] = now_iso
            topic_last = state.setdefault("topic_last_comment_at", {})
            topic_last[topic] = now_iso
            fact_last = state.setdefault("fact_last_comment_at", {})
            fact_last[fact_key] = now_iso
            hashes = list(state.get("semantic_hashes") or [])
            hashes.append(fact_digest)
            state["semantic_hashes"] = hashes
            append_recent_record(
                state,
                {
                    "at": now_iso,
                    "outcome": "intent",
                    "reason": "approved",
                    "topic": topic,
                    "fact": fact_key,
                    "intent": intent.model_dump(mode="json"),
                },
            )
            return CommentaryDecision(outcome="intent", reason="approved", intent=intent, candidate_fact=fact_key)

        decision = self.store.mutate(commit)
        return decision

    def record_spoken_line(self, text: str, intent: CommentIntent, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        digest = semantic_hash(text)

        def apply(state: dict[str, Any]) -> None:
            hashes = list(state.get("semantic_hashes") or [])
            hashes.append(digest)
            state["semantic_hashes"] = hashes
            append_recent_record(
                state,
                {
                    "at": _utc_iso(now),
                    "outcome": "spoken",
                    "reason": "delivered",
                    "topic": intent.topic,
                    "line_hash": digest,
                    "preview": text[:160],
                },
            )

        self.store.mutate(apply)

    def apply_feedback(self, body: CommentaryFeedbackRequest, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        def apply(state: dict[str, Any]) -> dict[str, Any]:
            if body.action == "more_like_this":
                state["preference_bias"] = min(3, int(state.get("preference_bias", 0)) + 1)
            elif body.action == "less_like_this":
                state["preference_bias"] = max(-3, int(state.get("preference_bias", 0)) - 1)
                state["last_global_comment_at"] = _utc_iso(now)
            elif body.action == "too_sarcastic":
                state["sarcasm_penalty_until"] = _utc_iso(now + timedelta(hours=24))
            elif body.action == "dont_comment_topic":
                topic = (body.topic or "").strip()
                if not topic:
                    raise ValueError("topic is required for dont_comment_topic")
                suppressed = state.setdefault("suppressed_topics", {})
                suppressed[topic] = _utc_iso(now + timedelta(days=30))
            append_recent_record(
                state,
                {
                    "at": _utc_iso(now),
                    "outcome": "feedback",
                    "reason": body.action,
                    "topic": body.topic,
                },
            )
            return {
                "ok": True,
                "action": body.action,
                "preference_bias": state.get("preference_bias", 0),
            }

        return self.store.mutate(apply)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        state = self.store.load()
        recent = list(state.get("recent") or [])
        return recent[-limit:]

    def status(self) -> dict[str, Any]:
        settings = self.settings
        store_snap = self.store.snapshot()
        return {
            "enabled": settings.enabled,
            "config": settings.model_dump(),
            "cooldowns_seconds": {
                "global": _FREQUENCY_COOLDOWNS_SECONDS[settings.comment_frequency][0],
                "topic": _FREQUENCY_COOLDOWNS_SECONDS[settings.comment_frequency][1],
            },
            **store_snap,
        }

    def _record_decision(
        self,
        candidate: ObservationCandidate,
        intent: CommentIntent | None,
        reason: str,
        now: datetime,
    ) -> None:
        def apply(state: dict[str, Any]) -> None:
            append_recent_record(
                state,
                {
                    "at": _utc_iso(now),
                    "outcome": "suppress",
                    "reason": reason,
                    "topic": topic_from_candidate(candidate),
                    "fact": candidate.fact,
                    "intent": intent.model_dump(mode="json") if intent else None,
                },
            )

        self.store.mutate(apply)

    def _category_allowed(self, candidate: ObservationCandidate) -> bool:
        mode = self.settings.personal_observations
        if mode == "disabled":
            return candidate.category in {"environment", "activity", "object"} and candidate.priority == "practical"
        if mode == "practical_only":
            if candidate.category == "appearance":
                return False
            if candidate.priority == "casual":
                return False
            return candidate.category in {"presence", "environment", "activity", "object"}
        if mode == "casual":
            if candidate.category == "appearance":
                return allowed_appearance_comment(candidate)
            return True
        if mode == "broad":
            if candidate.category == "appearance":
                return allowed_appearance_comment(candidate)
            return not fact_is_sensitive(candidate)
        return False

    def _guest_blocks_personal(self, candidate: ObservationCandidate, presence: CommentaryPresence) -> bool:
        if self.settings.allow_personal_with_guests:
            return False
        non_owner_context = (
            presence.unknown_guest_present
            or presence.person_count > 1
            or presence.identity_state in {"unknown", "provisional"}
            or (
                presence.identity_state == "confirmed"
                and presence.relationship not in {None, "owner"}
            )
        )
        if not non_owner_context:
            return False
        if candidate.category == "appearance":
            return True
        if candidate.priority == "casual":
            return True
        return False

    @staticmethod
    def _topic_suppressed(state: dict[str, Any], topic: str, now: datetime) -> bool:
        suppressed = state.get("suppressed_topics") or {}
        until = _parse_time(suppressed.get(topic))
        if until is None:
            return False
        return now < until

    @staticmethod
    def _sarcasm_penalty_active(state: dict[str, Any], now: datetime) -> bool:
        until = _parse_time(state.get("sarcasm_penalty_until"))
        return until is not None and now < until


def structured_counts_from_perception_state(
    perception_state: dict[str, Any],
    fact_key: str,
) -> dict[str, int]:
    facts = perception_state.get("facts") or {}
    record = facts.get(fact_key) or {}
    count = int(record.get("count", 0))
    out: dict[str, int] = {}
    if count >= 2:
        out["repeat_count_today"] = count
    return out


COMMENTARY_CHANNEL = "social-commentary"


async def publish_comment_intent(intent: CommentIntent) -> None:
    from ..events import BUS

    await BUS.publish_ephemeral(
        COMMENTARY_CHANNEL,
        "social_comment",
        intent.topic,
        json.dumps(intent.model_dump(mode="json")),
        stage="commentary",
    )
