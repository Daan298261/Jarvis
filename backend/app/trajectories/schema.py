from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SCHEMA_VERSION = "JarvisTrajectoryV1"


class TrajectoryProvenance(BaseModel):
    """Source identity for an imported or native trajectory."""

    harness: str
    harness_version: str | None = None
    model: str | None = None
    source_uri: str | None = None
    source_format: str | None = None
    imported_at: str
    import_id: str | None = None
    trusted: bool = False


class TrajectoryWorkspace(BaseModel):
    repository: str | None = None
    branch: str | None = None
    workspace_path: str | None = None


class TrajectoryEvent(BaseModel):
    sequence: int
    timestamp: str
    event_type: str
    content: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: str | None = None
    success: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrajectoryOutcome(BaseModel):
    """Distinguishes attempted work from validated success."""

    status: str
    attempted: bool = True
    verified: bool = False
    summary: str | None = None


class TrajectoryVerification(BaseModel):
    attempted: bool = False
    passed: bool = False
    details: str | None = None


class CandidateSkill(BaseModel):
    name: str | None = None
    tools: list[str] = Field(default_factory=list)
    description: str | None = None
    confidence: float = 0.0


class JarvisTrajectoryV1(BaseModel):
    schema_version: Literal["JarvisTrajectoryV1"] = SCHEMA_VERSION
    trajectory_id: str
    goal: str | None = None
    task_class: str | None = None
    provenance: TrajectoryProvenance
    workspace: TrajectoryWorkspace | None = None
    events: list[TrajectoryEvent]
    outcome: TrajectoryOutcome
    verification: TrajectoryVerification | None = None
    failures: list[str] = Field(default_factory=list)
    recovery: str | None = None
    candidate_skills: list[CandidateSkill] = Field(default_factory=list)
    duration_seconds: float | None = None
