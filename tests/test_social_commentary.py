from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.api import perception_commentary as commentary_api
from app.config import SocialCommentarySettings
from app.perception.commentary import CommentaryFeedbackRequest, CommentaryPresence, SocialCommentaryPolicy
from app.perception.commentary_store import CommentaryStateStore
from app.perception.models import ObservationCandidate
from app.persona.commentary_runtime import CommentaryActivitySnapshot, RUNTIME
from app.persona.social import (
    candidate_direct_speech_line,
    contains_forbidden_character_dialogue,
    is_direct_fact_speech,
    template_comment_for_intent,
    validate_generated_comment,
)


def _time(seconds: int = 0) -> datetime:
    return datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def _settings(**overrides) -> SocialCommentarySettings:
    base = {
        "enabled": True,
        "comment_frequency": "butler",
        "sarcasm": "dry",
        "personal_observations": "casual",
        "address_style": "sir_maam",
        "min_confidence": 0.75,
        "min_novelty": 0.35,
    }
    base.update(overrides)
    return SocialCommentarySettings(**base)


def _candidate(**overrides) -> ObservationCandidate:
    values = {
        "category": "appearance",
        "fact": "appearance.hair_state",
        "value": "dishevelled",
        "confidence": 0.86,
        "novelty": 0.71,
        "priority": "casual",
        "safe_to_comment": True,
        "reason": "changed_value",
        "observed_at": _time(),
    }
    values.update(overrides)
    return ObservationCandidate(**values)


def _owner_presence() -> CommentaryPresence:
    return CommentaryPresence(
        identity_state="confirmed",
        relationship="owner",
        person_count=1,
        unknown_guest_present=False,
    )


def test_commentary_settings_defaults_and_validation():
    settings = SocialCommentarySettings()
    assert settings.comment_frequency == "restrained"
    assert settings.sarcasm == "light"
    assert settings.personal_observations == "practical_only"

    with pytest.raises(ValidationError):
        SocialCommentarySettings(address_style="configured", configured_address_name="")


def test_candidate_cannot_speak_without_policy_gate(tmp_path):
    store = CommentaryStateStore(tmp_path / "commentary.json")
    policy = SocialCommentaryPolicy(_settings(), store)
    candidate = _candidate()

    raw_line = candidate_direct_speech_line(candidate)
    assert is_direct_fact_speech(raw_line, candidate)

    decision = policy.evaluate(candidate, presence=_owner_presence(), now=_time())
    assert decision.outcome == "intent"
    assert decision.intent is not None
    assert decision.intent.kind == "social_comment"
    assert decision.intent.topic == "appearance.hair_state"


def test_frequency_silent_suppresses(tmp_path):
    store = CommentaryStateStore(tmp_path / "commentary.json")
    policy = SocialCommentaryPolicy(_settings(comment_frequency="silent"), store)
    decision = policy.evaluate(_candidate(), presence=_owner_presence(), now=_time())
    assert decision.outcome == "suppress"
    assert decision.reason == "frequency_silent"


def test_global_and_topic_cooldowns(tmp_path):
    store = CommentaryStateStore(tmp_path / "commentary.json")
    policy = SocialCommentaryPolicy(_settings(comment_frequency="restrained"), store)

    first = policy.evaluate(_candidate(), presence=_owner_presence(), now=_time())
    assert first.outcome == "intent"

    second = policy.evaluate(
        _candidate(fact="environment.lighting", value="dim", category="environment", priority="practical"),
        presence=_owner_presence(),
        now=_time(60),
    )
    assert second.outcome == "suppress"
    assert second.reason == "global_cooldown"

    third = policy.evaluate(_candidate(), presence=_owner_presence(), now=_time(31 * 60))
    assert third.outcome == "suppress"
    assert third.reason == "topic_cooldown"


def test_interruption_gates_while_speaking(tmp_path):
    store = CommentaryStateStore(tmp_path / "commentary.json")
    policy = SocialCommentaryPolicy(_settings(), store)
    RUNTIME.update(
        user_speaking=False,
        jarvis_speaking=False,
        jarvis_listening_to_user=False,
        urgent_alert_active=False,
        high_priority_tool_active=False,
    )

    blocked = policy.evaluate(
        _candidate(),
        presence=_owner_presence(),
        activity=CommentaryActivitySnapshot(user_speaking=True),
        now=_time(),
    )
    assert blocked.outcome == "suppress"
    assert blocked.reason == "user_speaking"


def test_practical_not_urgent_for_appearance(tmp_path):
    store = CommentaryStateStore(tmp_path / "commentary.json")
    policy = SocialCommentaryPolicy(_settings(), store)
    decision = policy.evaluate(_candidate(), presence=_owner_presence(), now=_time())
    assert decision.intent is not None
    assert decision.intent.interruption_class == "casual"
    assert decision.intent.importance == "casual"


def test_guest_mode_suppresses_personal_appearance(tmp_path):
    store = CommentaryStateStore(tmp_path / "commentary.json")
    policy = SocialCommentaryPolicy(_settings(personal_observations="broad"), store)
    guest_presence = CommentaryPresence(
        identity_state="unknown",
        relationship=None,
        person_count=2,
        unknown_guest_present=True,
    )
    decision = policy.evaluate(_candidate(), presence=guest_presence, now=_time())
    assert decision.outcome == "suppress"
    assert decision.reason == "guest_privacy"


def test_practical_allowed_with_guests(tmp_path):
    store = CommentaryStateStore(tmp_path / "commentary.json")
    policy = SocialCommentaryPolicy(_settings(personal_observations="practical_only"), store)
    guest_presence = CommentaryPresence(identity_state="unknown", person_count=2, unknown_guest_present=True)
    decision = policy.evaluate(
        _candidate(
            category="environment",
            fact="environment.lighting",
            value="dim",
            priority="practical",
        ),
        presence=guest_presence,
        now=_time(),
    )
    assert decision.outcome == "intent"


def test_feedback_suppresses_topic(tmp_path):
    store = CommentaryStateStore(tmp_path / "commentary.json")
    policy = SocialCommentaryPolicy(_settings(), store)
    policy.apply_feedback(
        CommentaryFeedbackRequest(action="dont_comment_topic", topic="appearance.hair_state"),
        now=_time(),
    )
    decision = policy.evaluate(_candidate(), presence=_owner_presence(), now=_time(10))
    assert decision.outcome == "suppress"
    assert decision.reason == "topic_feedback_suppressed"


def test_forbidden_content_and_fabrication_guards():
    candidate = _candidate()
    ok, reason = validate_generated_comment(
        "Your hair appears to have adopted a rather independent strategy this morning, sir.",
        candidate,
    )
    assert ok and reason == "ok"

    bad_direct, reason_direct = validate_generated_comment(candidate_direct_speech_line(candidate), candidate)
    assert not bad_direct and reason_direct == "direct_fact_speech"

    bad_count, reason_count = validate_generated_comment("That is your third cup today, sir.", candidate)
    assert not bad_count and reason_count == "fabricated_count"

    bad_fallout, reason_fallout = validate_generated_comment(
        "Ready to serve your every need, as Codsworth would say.",
        candidate,
    )
    assert not bad_fallout and reason_fallout == "forbidden_character_dialogue"
    assert contains_forbidden_character_dialogue("Mr. Handy reporting for duty")


def test_template_uses_structured_repeat_count_only():
    intent = {
        "topic": "object.coffee_mug",
        "value": True,
        "tone": "dry",
        "address_style": "sir_maam",
        "context": {"repeat_count_today": 3},
    }
    line = template_comment_for_intent(intent)
    assert line is not None
    assert "third" not in line.lower()
    ok, _ = validate_generated_comment(line, _candidate(fact="object.coffee_mug", category="object", priority="practical"))
    assert ok


def test_commentary_api_routes_exist():
    paths = {route.path for route in commentary_api.router.routes}
    assert "/api/perception/commentary/status" in paths
    assert "/api/perception/commentary/recent" in paths
    assert "/api/perception/commentary/feedback" in paths
    assert "/api/perception/commentary/evaluate" in paths
