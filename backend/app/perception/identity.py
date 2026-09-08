from __future__ import annotations

import math
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import IdentityRecognitionSettings
from .identity_store import IdentityEnrollment, IdentityStore

Relationship = Literal["owner", "household_member", "trusted_person"]
IdentityState = Literal["disabled", "unknown", "provisional", "confirmed"]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class IdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrollmentSessionRequest(IdentityModel):
    """Owner intent only. Biometric samples never cross this HTTP model."""

    identity_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    relationship: Relationship
    embedding_model: str = Field(default="sface-2021dec", min_length=1, max_length=80)
    embedding_version: int = Field(default=1, ge=1, le=1000)

    @field_validator("identity_id")
    @classmethod
    def validate_identity_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not _ID_RE.fullmatch(value):
            raise ValueError("identity_id must be a lowercase slug using letters, numbers, _ or -")
        return value

    @field_validator("display_name", "embedding_model")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("value must not be empty")
        return value


class EnrollmentSession(IdentityModel):
    session_id: str
    identity_id: str
    display_name: str
    relationship: Relationship
    embedding_model: str
    embedding_version: int
    created_at: datetime
    expires_at: datetime


class EnrollmentSummary(IdentityModel):
    identity_id: str
    display_name: str
    relationship: Relationship
    created_at: datetime
    embedding_model: str
    embedding_version: int
    samples: int = Field(ge=1)


class IdentityResolution(IdentityModel):
    state: IdentityState
    identity_id: str | None = None
    relationship: Relationship | None = None
    confidence: float | None = Field(default=None, ge=-1.0, le=1.0)
    observed_at: datetime
    reason: str


@dataclass
class _TrackState:
    history: deque[str | None]
    confirmed_identity: str | None = None
    confirmed_at: datetime | None = None
    last_strong_seen_at: datetime | None = None


@dataclass
class IdentityResolver:
    """Local-only embedding matcher.

    The resolver accepts numeric embeddings produced by a trusted local camera/model
    adapter. It never accepts image bytes, performs network calls, or exposes a
    general-purpose face-search endpoint.
    """

    settings: IdentityRecognitionSettings
    store: IdentityStore
    _tracks: dict[str, _TrackState] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def enroll_embeddings(
        self,
        request: EnrollmentSessionRequest,
        embeddings: Iterable[Iterable[float]],
    ) -> EnrollmentSummary:
        """Persist already-computed embeddings from a trusted local enrollment flow."""
        normalized = [_normalize_embedding(vector) for vector in embeddings]
        if not normalized:
            raise ValueError("at least one embedding sample is required")
        if len(normalized) > 20:
            raise ValueError("at most 20 embedding samples may be enrolled")
        dimension = len(normalized[0])
        if dimension < 8 or dimension > 4096:
            raise ValueError("embedding dimension must be between 8 and 4096")
        if any(len(vector) != dimension for vector in normalized):
            raise ValueError("all embedding samples must have the same dimension")

        enrollment = IdentityEnrollment(
            identity_id=request.identity_id,
            display_name=request.display_name,
            relationship=request.relationship,
            created_at=datetime.now(timezone.utc),
            embedding_model=request.embedding_model,
            embedding_version=request.embedding_version,
            embeddings=normalized,
        )
        self.store.upsert(enrollment)
        return _summary(enrollment)

    def resolve_embedding(
        self,
        embedding: Iterable[float] | None,
        *,
        quality: float,
        observed_at: datetime | None = None,
        track_id: str = "primary",
    ) -> IdentityResolution:
        now = observed_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)

        with self._lock:
            track = self._tracks.setdefault(
                track_id,
                _TrackState(history=deque(maxlen=self.settings.confirmation_window)),
            )

            if not self.settings.enabled:
                self._tracks.pop(track_id, None)
                return IdentityResolution(
                    state="disabled",
                    observed_at=now,
                    reason="recognition_disabled",
                )

            if embedding is None or quality < self.settings.min_face_quality:
                return self._handle_unknown(track, now, reason="insufficient_face_quality")

            vector = _normalize_embedding(embedding)
            enrollments = self.store.list_all()
            compatible = [item for item in enrollments if item.embeddings and len(item.embeddings[0]) == len(vector)]
            if not compatible:
                return self._handle_unknown(track, now, reason="no_compatible_enrollments")

            ranked: list[tuple[float, IdentityEnrollment]] = []
            for enrollment in compatible:
                score = max(_cosine(vector, sample) for sample in enrollment.embeddings)
                ranked.append((score, enrollment))
            ranked.sort(key=lambda item: item[0], reverse=True)

            best_score, best = ranked[0]
            second_score = ranked[1][0] if len(ranked) > 1 else -1.0
            margin = best_score - second_score

            if best_score < self.settings.match_threshold:
                return self._handle_unknown(track, now, reason="below_match_threshold")
            if len(ranked) > 1 and margin < self.settings.margin_threshold:
                return self._handle_unknown(track, now, reason="ambiguous_match")

            track.history.append(best.identity_id)
            hits = sum(1 for value in track.history if value == best.identity_id)
            if hits >= self.settings.confirmation_hits:
                track.confirmed_identity = best.identity_id
                track.confirmed_at = now
                track.last_strong_seen_at = now
                return IdentityResolution(
                    state="confirmed",
                    identity_id=best.identity_id,
                    relationship=best.relationship,
                    confidence=best_score,
                    observed_at=now,
                    reason="temporal_confirmation",
                )

            # If the same identity is already confirmed, keep it confirmed while
            # receiving continued strong matches rather than dropping to provisional.
            if track.confirmed_identity == best.identity_id:
                track.last_strong_seen_at = now
                return IdentityResolution(
                    state="confirmed",
                    identity_id=best.identity_id,
                    relationship=best.relationship,
                    confidence=best_score,
                    observed_at=now,
                    reason="confirmed_continuation",
                )

            return IdentityResolution(
                state="provisional",
                identity_id=best.identity_id,
                relationship=best.relationship,
                confidence=best_score,
                observed_at=now,
                reason="awaiting_temporal_confirmation",
            )

    def delete_identity(self, identity_id: str) -> bool:
        deleted = self.store.delete(identity_id)
        if deleted:
            self.clear_identity_state(identity_id)
        return deleted

    def reset(self) -> None:
        self.store.reset()
        with self._lock:
            self._tracks.clear()

    def clear_identity_state(self, identity_id: str) -> None:
        with self._lock:
            for track_id, state in list(self._tracks.items()):
                if state.confirmed_identity == identity_id or identity_id in state.history:
                    self._tracks.pop(track_id, None)

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.settings.enabled,
            "backend": self.settings.backend,
            "enrollment_count": self.store.count(),
            "encrypted_at_rest": self.store.encrypted_at_rest,
            "active_track_count": len(self._tracks),
        }

    def _handle_unknown(self, track: _TrackState, now: datetime, *, reason: str) -> IdentityResolution:
        track.history.append(None)
        if track.confirmed_identity and track.last_strong_seen_at:
            elapsed = max(0.0, (now - track.last_strong_seen_at).total_seconds())
            if elapsed <= self.settings.lost_timeout_seconds:
                enrollment = self.store.get(track.confirmed_identity)
                if enrollment is not None:
                    return IdentityResolution(
                        state="confirmed",
                        identity_id=enrollment.identity_id,
                        relationship=enrollment.relationship,
                        observed_at=now,
                        reason="short_occlusion_hold",
                    )
        track.confirmed_identity = None
        track.confirmed_at = None
        track.last_strong_seen_at = None
        return IdentityResolution(state="unknown", observed_at=now, reason=reason)


def list_summaries(store: IdentityStore) -> list[EnrollmentSummary]:
    return [_summary(item) for item in store.list_all()]


def _summary(enrollment: IdentityEnrollment) -> EnrollmentSummary:
    return EnrollmentSummary(
        identity_id=enrollment.identity_id,
        display_name=enrollment.display_name,
        relationship=enrollment.relationship,
        created_at=enrollment.created_at,
        embedding_model=enrollment.embedding_model,
        embedding_version=enrollment.embedding_version,
        samples=len(enrollment.embeddings),
    )


def _normalize_embedding(values: Iterable[float]) -> list[float]:
    vector = [float(value) for value in values]
    if not vector:
        raise ValueError("embedding must not be empty")
    if any(not math.isfinite(value) for value in vector):
        raise ValueError("embedding values must be finite")
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-12:
        raise ValueError("embedding norm must be non-zero")
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right))))
