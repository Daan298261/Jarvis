from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.api import perception as perception_api
from app.api.settings import SettingsUpdate
from app.config import SocialPerceptionSettings
from app.perception.models import AppearanceObservation, EnvironmentObservation, StructuredObservation
from app.perception.policy import PerceptionPolicy
from app.perception.store import PerceptionStateStore


def _settings(**overrides) -> SocialPerceptionSettings:
    values = {
        "enabled": True,
        "min_confidence": 0.75,
        "novelty_threshold": 0.35,
        "comment_cooldown_seconds": 0,
        "duplicate_ttl_seconds": 3600,
        "baseline_enabled": True,
    }
    values.update(overrides)
    return SocialPerceptionSettings(**values)


def _time(seconds: int = 0) -> datetime:
    return datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_social_perception_defaults_off_and_ranges_are_validated():
    settings = SocialPerceptionSettings()
    assert settings.enabled is False
    assert settings.semantic_observer == "none"
    assert settings.min_confidence == 0.75

    with pytest.raises(ValidationError):
        SocialPerceptionSettings(min_confidence=1.1)
    with pytest.raises(ValidationError):
        SocialPerceptionSettings(sample_interval_seconds=0.1)
    with pytest.raises(ValidationError):
        SocialPerceptionSettings(max_summary_retention_hours=0)

    with pytest.raises(ValidationError):
        SettingsUpdate(social_perception_novelty_threshold=-0.01)


def test_observation_schema_forbids_sensitive_or_unknown_fields():
    with pytest.raises(ValidationError):
        StructuredObservation.model_validate(
            {
                "confidence": 0.9,
                "person_present": True,
                "ethnicity": "inferred-value",
            }
        )

    with pytest.raises(ValidationError):
        StructuredObservation.model_validate(
            {
                "confidence": 0.9,
                "attributes": {"medical_condition": 0.95},
            }
        )


def test_observation_schema_bounds_free_text():
    with pytest.raises(ValidationError):
        AppearanceObservation(clothing_summary="x" * 121)

    with pytest.raises(ValidationError):
        StructuredObservation(confidence=0.9, objects=["x" * 49])


def test_disabled_policy_does_not_persist_observation(tmp_path):
    path = tmp_path / "perception.json"
    store = PerceptionStateStore(path)
    result = PerceptionPolicy(SocialPerceptionSettings(enabled=False), store).evaluate(
        StructuredObservation(confidence=0.99, person_present=True, observed_at=_time())
    )

    assert result.accepted is False
    assert result.reason == "disabled"
    assert result.candidates == []
    assert not path.exists()


def test_low_confidence_is_rejected_before_fact_or_baseline_storage(tmp_path):
    store = PerceptionStateStore(tmp_path / "perception.json")
    result = PerceptionPolicy(_settings(min_confidence=0.8), store).evaluate(
        StructuredObservation(
            confidence=0.79,
            appearance=AppearanceObservation(hair_state="dishevelled"),
            observed_at=_time(),
        )
    )

    assert result.accepted is True
    assert result.reason == "no_candidate"
    assert result.candidates == []
    snapshot = store.snapshot()
    assert snapshot["fact_count"] == 0
    assert snapshot["baseline_fact_count"] == 0


def test_repeated_identical_observation_is_suppressed(tmp_path):
    store = PerceptionStateStore(tmp_path / "perception.json")
    policy = PerceptionPolicy(_settings(), store)

    first = policy.evaluate(
        StructuredObservation(
            confidence=0.9,
            appearance=AppearanceObservation(hair_state="tidy"),
            observed_at=_time(),
        )
    )
    second = policy.evaluate(
        StructuredObservation(
            confidence=0.95,
            appearance=AppearanceObservation(hair_state="tidy"),
            observed_at=_time(10),
        )
    )

    assert first.reason == "candidate"
    assert first.candidates[0].fact == "appearance.hair_state"
    assert second.reason == "no_candidate"
    assert second.candidates == []


def test_changed_value_emits_even_inside_duplicate_ttl(tmp_path):
    store = PerceptionStateStore(tmp_path / "perception.json")
    policy = PerceptionPolicy(_settings(duplicate_ttl_seconds=3600), store)

    policy.evaluate(
        StructuredObservation(
            confidence=0.9,
            appearance=AppearanceObservation(hair_state="tidy"),
            observed_at=_time(),
        )
    )
    changed = policy.evaluate(
        StructuredObservation(
            confidence=0.91,
            appearance=AppearanceObservation(hair_state="dishevelled"),
            observed_at=_time(30),
        )
    )

    assert changed.reason == "candidate"
    candidate = changed.candidates[0]
    assert candidate.fact == "appearance.hair_state"
    assert candidate.value == "dishevelled"
    assert candidate.reason == "changed_value"
    assert candidate.novelty >= 0.6


def test_global_cooldown_suppresses_new_candidate(tmp_path):
    store = PerceptionStateStore(tmp_path / "perception.json")
    policy = PerceptionPolicy(_settings(comment_cooldown_seconds=900), store)

    first = policy.evaluate(
        StructuredObservation(
            confidence=0.9,
            appearance=AppearanceObservation(hair_state="tidy"),
            observed_at=_time(),
        )
    )
    second = policy.evaluate(
        StructuredObservation(
            confidence=0.95,
            environment=EnvironmentObservation(lighting="dim"),
            observed_at=_time(60),
        )
    )

    assert first.reason == "candidate"
    assert second.reason == "global_cooldown"
    assert second.candidates == []


def test_attribute_confidence_can_reject_one_fact(tmp_path):
    store = PerceptionStateStore(tmp_path / "perception.json")
    policy = PerceptionPolicy(_settings(min_confidence=0.8), store)

    result = policy.evaluate(
        StructuredObservation(
            confidence=0.95,
            appearance=AppearanceObservation(hair_state="dishevelled"),
            environment=EnvironmentObservation(lighting="dim"),
            attributes={
                "hair_state": 0.4,
                "lighting": 0.92,
            },
            observed_at=_time(),
        )
    )

    assert result.reason == "candidate"
    assert result.candidates[0].fact == "environment.lighting"
    state = store.load()
    assert "appearance.hair_state" not in state["facts"]
    assert "environment.lighting" in state["facts"]


def test_candidate_and_persisted_state_contain_no_frame_data(tmp_path):
    store = PerceptionStateStore(tmp_path / "perception.json")
    result = PerceptionPolicy(_settings(), store).evaluate(
        StructuredObservation(
            source="camera.frontend",
            confidence=0.9,
            person_present=True,
            objects=["coffee mug"],
            observed_at=_time(),
        )
    )

    dumped = result.model_dump(mode="json")
    state_text = (tmp_path / "perception.json").read_text(encoding="utf-8")
    assert "image" not in str(dumped).lower()
    assert "frame" not in str(dumped).lower()
    assert "base64" not in state_text.lower()
    assert "image" not in state_text.lower()
    assert "frame" not in state_text.lower()


def test_baseline_and_transient_state_reset_independently(tmp_path):
    store = PerceptionStateStore(tmp_path / "perception.json")
    policy = PerceptionPolicy(_settings(), store)
    policy.evaluate(
        StructuredObservation(
            confidence=0.9,
            appearance=AppearanceObservation(hair_state="tidy"),
            observed_at=_time(),
        )
    )

    assert store.snapshot()["fact_count"] == 1
    assert store.snapshot()["baseline_fact_count"] == 1

    store.reset_state()
    assert store.snapshot()["fact_count"] == 0
    assert store.snapshot()["baseline_fact_count"] == 1

    store.reset_baseline()
    assert store.snapshot()["baseline_fact_count"] == 0


def test_perception_router_has_structured_endpoints_only():
    paths = {route.path for route in perception_api.router.routes}
    assert "/api/perception/status" in paths
    assert "/api/perception/observations" in paths
    assert "/api/perception/baseline/reset" in paths
    assert "/api/perception/state/reset" in paths
    assert not any("image" in path or "frame" in path for path in paths)
