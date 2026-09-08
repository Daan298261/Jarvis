from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.api import perception_identity
from app.config import IdentityRecognitionSettings
from app.perception.identity import EnrollmentSessionRequest, IdentityResolver
from app.perception.identity_store import IdentityStore


def _vector(*values: float) -> list[float]:
    padded = list(values)
    while len(padded) < 8:
        padded.append(0.0)
    return padded


def _request(identity_id: str = "owner", name: str = "Owner", relationship: str = "owner"):
    return EnrollmentSessionRequest(
        identity_id=identity_id,
        display_name=name,
        relationship=relationship,
        embedding_model="test-model",
        embedding_version=1,
    )


def _resolver(tmp_path, **overrides) -> IdentityResolver:
    values = {
        "enabled": True,
        "backend": "test",
        "match_threshold": 0.80,
        "margin_threshold": 0.08,
        "min_face_quality": 0.60,
        "confirmation_window": 5,
        "confirmation_hits": 3,
        "lost_timeout_seconds": 3.0,
    }
    values.update(overrides)
    settings = IdentityRecognitionSettings(**values)
    store = IdentityStore(tmp_path / "identities.enc", tmp_path / "identities.key")
    return IdentityResolver(settings, store)


def _time(seconds: float = 0.0) -> datetime:
    return datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_identity_recognition_defaults_disabled_and_validates_confirmation_window():
    settings = IdentityRecognitionSettings()
    assert settings.enabled is False
    assert settings.backend == "none"

    with pytest.raises(ValidationError):
        IdentityRecognitionSettings(confirmation_window=2, confirmation_hits=3)


def test_enrollment_http_model_forbids_images_and_embeddings():
    with pytest.raises(ValidationError):
        EnrollmentSessionRequest.model_validate(
            {
                "identity_id": "owner",
                "display_name": "Owner",
                "relationship": "owner",
                "image": "data:image/jpeg;base64,...",
            }
        )

    with pytest.raises(ValidationError):
        EnrollmentSessionRequest.model_validate(
            {
                "identity_id": "owner",
                "display_name": "Owner",
                "relationship": "owner",
                "embeddings": [[1.0, 0.0]],
            }
        )


def test_identity_id_is_constrained_slug():
    assert _request("housemate_1", "Housemate", "household_member").identity_id == "housemate_1"
    with pytest.raises(ValidationError):
        _request("../../owner")


def test_store_encrypts_embedding_payload_and_metadata(tmp_path):
    resolver = _resolver(tmp_path)
    resolver.enroll_embeddings(_request(), [_vector(1.0)])

    encrypted = (tmp_path / "identities.enc").read_bytes()
    assert b"Owner" not in encrypted
    assert b"owner" not in encrypted
    assert b"embedding" not in encrypted.lower()
    assert (tmp_path / "identities.key").exists()

    loaded = resolver.store.get("owner")
    assert loaded is not None
    assert loaded.display_name == "Owner"
    assert len(loaded.embeddings) == 1
    assert len(loaded.embeddings[0]) == 8


def test_disabled_recognition_never_matches(tmp_path):
    resolver = _resolver(tmp_path, enabled=False)
    resolver.enroll_embeddings(_request(), [_vector(1.0)])

    result = resolver.resolve_embedding(_vector(1.0), quality=1.0, observed_at=_time())
    assert result.state == "disabled"
    assert result.identity_id is None


def test_low_face_quality_returns_unknown(tmp_path):
    resolver = _resolver(tmp_path)
    resolver.enroll_embeddings(_request(), [_vector(1.0)])

    result = resolver.resolve_embedding(_vector(1.0), quality=0.2, observed_at=_time())
    assert result.state == "unknown"
    assert result.reason == "insufficient_face_quality"


def test_below_match_threshold_stays_unknown(tmp_path):
    resolver = _resolver(tmp_path, match_threshold=0.90)
    resolver.enroll_embeddings(_request(), [_vector(1.0)])

    result = resolver.resolve_embedding(_vector(0.0, 1.0), quality=1.0, observed_at=_time())
    assert result.state == "unknown"
    assert result.reason == "below_match_threshold"


def test_ambiguous_second_best_margin_stays_unknown(tmp_path):
    resolver = _resolver(tmp_path, match_threshold=0.80, margin_threshold=0.08)
    resolver.enroll_embeddings(_request("owner", "Owner", "owner"), [_vector(1.0, 0.0)])
    resolver.enroll_embeddings(
        _request("housemate", "Housemate", "household_member"),
        [_vector(0.99, 0.10)],
    )

    result = resolver.resolve_embedding(_vector(1.0, 0.0), quality=1.0, observed_at=_time())
    assert result.state == "unknown"
    assert result.reason == "ambiguous_match"


def test_temporal_confirmation_requires_multiple_hits(tmp_path):
    resolver = _resolver(tmp_path, confirmation_window=5, confirmation_hits=3)
    resolver.enroll_embeddings(_request(), [_vector(1.0)])

    first = resolver.resolve_embedding(_vector(1.0), quality=1.0, observed_at=_time(0))
    second = resolver.resolve_embedding(_vector(1.0), quality=1.0, observed_at=_time(1))
    third = resolver.resolve_embedding(_vector(1.0), quality=1.0, observed_at=_time(2))

    assert first.state == "provisional"
    assert second.state == "provisional"
    assert third.state == "confirmed"
    assert third.identity_id == "owner"
    assert third.relationship == "owner"


def test_short_occlusion_holds_confirmed_identity_then_times_out(tmp_path):
    resolver = _resolver(tmp_path, confirmation_hits=2, lost_timeout_seconds=3.0)
    resolver.enroll_embeddings(_request(), [_vector(1.0)])
    resolver.resolve_embedding(_vector(1.0), quality=1.0, observed_at=_time(0))
    confirmed = resolver.resolve_embedding(_vector(1.0), quality=1.0, observed_at=_time(1))
    assert confirmed.state == "confirmed"

    held = resolver.resolve_embedding(None, quality=0.0, observed_at=_time(2))
    assert held.state == "confirmed"
    assert held.identity_id == "owner"
    assert held.reason == "short_occlusion_hold"

    lost = resolver.resolve_embedding(None, quality=0.0, observed_at=_time(5))
    assert lost.state == "unknown"
    assert lost.identity_id is None


def test_delete_identity_removes_embedding_and_cached_confirmation(tmp_path):
    resolver = _resolver(tmp_path, confirmation_hits=1)
    resolver.enroll_embeddings(_request(), [_vector(1.0)])
    matched = resolver.resolve_embedding(_vector(1.0), quality=1.0, observed_at=_time())
    assert matched.state == "confirmed"

    assert resolver.delete_identity("owner") is True
    assert resolver.store.get("owner") is None

    after = resolver.resolve_embedding(_vector(1.0), quality=1.0, observed_at=_time(1))
    assert after.state == "unknown"
    assert after.reason == "no_compatible_enrollments"


def test_reset_deletes_all_recognition_data(tmp_path):
    resolver = _resolver(tmp_path)
    resolver.enroll_embeddings(_request(), [_vector(1.0)])
    resolver.enroll_embeddings(
        _request("housemate", "Housemate", "household_member"),
        [_vector(0.0, 1.0)],
    )
    assert resolver.store.count() == 2

    resolver.reset()
    assert resolver.store.count() == 0
    assert not (tmp_path / "identities.enc").exists()


def test_router_exposes_management_not_face_search_or_image_upload():
    paths = {route.path for route in perception_identity.router.routes}
    assert "/api/perception/identity/status" in paths
    assert "/api/perception/identity/enrollments" in paths
    assert "/api/perception/identity/enrollments/{identity_id}" in paths
    assert "/api/perception/identity/reset" in paths
    assert not any("match" in path or "search" in path or "image" in path or "embedding" in path for path in paths)
    assert not any(path.startswith("/api/guest/") for path in paths)
