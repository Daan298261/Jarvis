"""Skill Forge schemas — manifests, versions, lifecycle (RFC-0173 / RFC-0024)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LifecycleStatus(str, Enum):
    PROPOSED = "proposed"
    SANDBOXED = "sandboxed"
    VERIFIED = "verified"
    APPROVED = "approved"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    QUARANTINED = "quarantined"


class SkillScope(str, Enum):
    GLOBAL = "global"
    DOMAIN = "domain"
    PROJECT = "project"
    REPOSITORY = "repository"
    WORKFLOW = "workflow"
    AGENT = "agent"


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    PATH = "path"
    URL = "url"
    SECRET = "secret"
    OBJECT = "object"
    ARRAY = "array"


class TypedField(BaseModel):
    name: str
    type: FieldType = FieldType.STRING
    description: str = ""
    required: bool = True
    examples: list[str] = Field(default_factory=list)


class SkillStep(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class DeterministicTest(BaseModel):
    """A fixture-backed acceptance test. Inputs are parameter bindings; golden is exact criteria."""

    id: str
    description: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_tools: list[str] = Field(default_factory=list)
    expected_step_count: int | None = None
    golden_outputs: list[dict[str, Any]] = Field(default_factory=list)
    require_success: bool = True


class VerifierResult(BaseModel):
    passed: bool
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    details: list[dict[str, Any]] = Field(default_factory=list)
    isolated_workspace: str | None = None
    evaluated_at: str | None = None


class Provenance(BaseModel):
    source: Literal["trace", "owner_request", "repair", "marketplace", "import"] = "trace"
    trajectory_ids: list[str] = Field(default_factory=list)
    parent_version_id: str | None = None
    created_by: str = "skill_forge"
    imported_from: str | None = None
    notes: str = ""


class SkillManifest(BaseModel):
    """Typed skill declaration. Effective permissions are never self-granted."""

    name: str
    purpose: str = ""
    version: str = "0.1.0"
    scope: SkillScope = SkillScope.WORKFLOW
    task_class: str = ""
    inputs: list[TypedField] = Field(default_factory=list)
    outputs: list[TypedField] = Field(default_factory=list)
    steps: list[SkillStep] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    network_scope: list[str] = Field(default_factory=list)
    filesystem_scope: list[str] = Field(default_factory=list)
    compatible_personas: list[str] = Field(default_factory=list)
    compatible_models: list[str] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    tests: list[DeterministicTest] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    rollback_target_version_id: str | None = None
    content_hash: str = ""
    signature: str = ""

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("skill name is required")
        return cleaned[:120]


class SkillVersion(BaseModel):
    """Immutable skill version record once activated."""

    version_id: str
    skill_id: str
    status: LifecycleStatus
    manifest: SkillManifest
    verifier: VerifierResult | None = None
    effective_capabilities: list[str] = Field(default_factory=list)
    approval: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    activated_at: str | None = None
    disabled: bool = False
    quarantine_reason: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    immutable: bool = False


class SkillCandidate(BaseModel):
    """Lifecycle-tracked candidate. Activation never mutates an active version in place."""

    candidate_id: str
    skill_id: str
    status: LifecycleStatus = LifecycleStatus.PROPOSED
    version: SkillVersion
    created_at: str
    updated_at: str
    decision_inbox_item_id: str | None = None
    rejection_reason: str | None = None


class SkillRegistryEntry(BaseModel):
    skill_id: str
    name: str
    active_version_id: str | None = None
    versions: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    origin: str = "forge"
