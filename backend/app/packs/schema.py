from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

PACK_SCHEMA_VERSION = "1.0"

RESOURCE_TYPES = frozenset(
    {
        "workflow",
        "policy",
        "agent_profile",
        "goal",
        "knowledge",
        "integration",
        "metric",
        "ui_default",
        "tool",
    }
)

MERGE_STRATEGIES = frozenset({"replace", "merge", "skip_if_user_modified"})
TRUST_LEVELS = frozenset({"user", "verified", "untrusted"})
RESOURCE_ACTIONS = frozenset({"create", "update", "skip", "conflict", "delete"})

_SEMVER_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:[-+].*)?$"
)


def parse_version(value: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"Invalid semver: {value!r}")
    return int(match.group("major")), int(match.group("minor")), int(match.group("patch"))


def version_satisfies(current: str, requirement: str) -> bool:
    """Evaluate simple semver requirements: *, >=x.y.z, ==x.y.z, >x.y.z, <=x.y.z."""
    req = (requirement or "*").strip()
    if req in {"", "*"}:
        return True
    current_tuple = parse_version(current)
    if req.startswith(">="):
        return current_tuple >= parse_version(req[2:].strip())
    if req.startswith("<="):
        return current_tuple <= parse_version(req[2:].strip())
    if req.startswith(">"):
        return current_tuple > parse_version(req[1:].strip())
    if req.startswith("<"):
        return current_tuple < parse_version(req[1:].strip())
    if req.startswith("=="):
        return current_tuple == parse_version(req[2:].strip())
    return current_tuple == parse_version(req)


class PackDependency(BaseModel):
    id: str
    version: str = "*"
    optional: bool = False


class PackTrust(BaseModel):
    signature: str | None = None
    signer_key_id: str | None = None
    trust_level: Literal["user", "verified", "untrusted"] = "user"


class PackCapabilities(BaseModel):
    required_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)


class PackResource(BaseModel):
    id: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    merge_strategy: Literal["replace", "merge", "skip_if_user_modified"] = "replace"

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in RESOURCE_TYPES:
            raise ValueError(f"Unsupported resource type: {value!r}")
        return normalized


class PackManifest(BaseModel):
    schema_version: str = PACK_SCHEMA_VERSION
    id: str
    name: str
    version: str
    description: str = ""
    min_jarvis_version: str = "1.0.0"
    dependencies: list[PackDependency] = Field(default_factory=list)
    trust: PackTrust = Field(default_factory=PackTrust)
    capabilities: PackCapabilities = Field(default_factory=PackCapabilities)
    resources: list[PackResource] = Field(default_factory=list)
    ui_defaults: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != PACK_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported pack schema_version {value!r}; expected {PACK_SCHEMA_VERSION!r}"
            )
        return value

    @field_validator("version", "min_jarvis_version")
    @classmethod
    def validate_semver(cls, value: str) -> str:
        parse_version(value)
        return value

    def model_dump_canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ResourceChange(BaseModel):
    resource_id: str
    resource_type: str
    action: Literal["create", "update", "skip", "conflict", "delete"]
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str = ""


class PackPreview(BaseModel):
    pack_id: str
    version: str
    action: Literal["install", "upgrade", "uninstall"]
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    changes: list[ResourceChange] = Field(default_factory=list)
    trust: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    dependencies: dict[str, Any] = Field(default_factory=dict)


class InstalledPack(BaseModel):
    id: str
    name: str
    version: str
    description: str = ""
    status: Literal["installed", "rolled_back"] = "installed"
    installed_at: str
    manifest_hash: str = ""
    previous_version: str | None = None
    snapshot_id: str | None = None
    resource_ids: list[str] = Field(default_factory=list)


class ResourceRecord(BaseModel):
    resource_id: str
    pack_id: str
    resource_type: str
    user_modified: bool = False
    override: Literal["keep_user", "use_pack", "merge"] | None = None
    data_hash: str = ""
    installed_version: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
