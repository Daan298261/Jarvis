from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HairState = Literal["tidy", "dishevelled", "wet", "covered"]
LightingState = Literal["dark", "dim", "normal", "bright"]
ActivityState = Literal[
    "sitting",
    "standing",
    "walking",
    "working_at_computer",
    "reading",
    "eating",
    "drinking",
]
CandidateCategory = Literal["presence", "environment", "activity", "object", "appearance"]
CandidatePriority = Literal["practical", "social", "casual"]

_ALLOWED_ATTRIBUTE_KEYS = {
    "person.present",
    "person.count",
    "appearance.hair_state",
    "appearance.glasses",
    "appearance.clothing_summary",
    "activity",
    "environment.lighting",
    # Tolerate the short aliases used by small local observers while keeping the
    # field allowlisted and bounded.
    "hair_state",
    "glasses",
    "clothing_summary",
    "lighting",
}


class StrictObservationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppearanceObservation(StrictObservationModel):
    hair_state: HairState | None = None
    glasses: bool | None = None
    clothing_summary: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("clothing_summary")
    @classmethod
    def normalize_clothing_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("clothing_summary must contain visible clothing details")
        return value


class EnvironmentObservation(StrictObservationModel):
    lighting: LightingState | None = None


class StructuredObservation(StrictObservationModel):
    """A bounded semantic snapshot with no raw image/frame payload."""

    source: str = Field(default="camera.frontend", min_length=1, max_length=64)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    person_present: bool | None = None
    person_count: int | None = Field(default=None, ge=0, le=10)
    appearance: AppearanceObservation | None = None
    activity: ActivityState | None = None
    objects: list[str] = Field(default_factory=list, max_length=12)
    environment: EnvironmentObservation | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    attributes: dict[str, float] = Field(default_factory=dict, max_length=32)

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source must not be empty")
        return value

    @field_validator("objects")
    @classmethod
    def validate_objects(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in values:
            if not isinstance(raw, str):
                raise ValueError("objects must contain strings")
            value = " ".join(raw.split()).strip().lower()
            if not value or len(value) > 48:
                raise ValueError("object labels must be 1-48 characters")
            if value not in seen:
                cleaned.append(value)
                seen.add(value)
        return cleaned

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, values: dict[str, float]) -> dict[str, float]:
        for key, confidence in values.items():
            if key not in _ALLOWED_ATTRIBUTE_KEYS and not key.startswith("object."):
                raise ValueError(f"unsupported observation confidence key: {key}")
            if len(key) > 80:
                raise ValueError("observation confidence keys must be <= 80 characters")
            if not 0.0 <= float(confidence) <= 1.0:
                raise ValueError("attribute confidence must be between 0 and 1")
        return values


class ObservationCandidate(StrictObservationModel):
    kind: Literal["social_observation_candidate"] = "social_observation_candidate"
    category: CandidateCategory
    fact: str = Field(min_length=1, max_length=96)
    value: str | bool | int = Field()
    confidence: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    priority: CandidatePriority
    safe_to_comment: bool = True
    reason: Literal["first_seen", "changed_value"]
    observed_at: datetime


class PolicyResult(StrictObservationModel):
    accepted: bool
    reason: str
    candidates: list[ObservationCandidate] = Field(default_factory=list, max_length=8)
    evaluated_facts: int = Field(default=0, ge=0)
