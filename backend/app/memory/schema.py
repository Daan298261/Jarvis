from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "JarvisContextRepoV1"

ENTRY_CATEGORIES = (
    "identity",
    "projects",
    "procedures",
    "lessons",
    "priorities",
    "skills",
)


class EntryProvenance(BaseModel):
    """Source identity for a curated context entry or mutation."""

    source_type: str
    source_id: str | None = None
    trajectory_id: str | None = None
    mutation_id: str | None = None
    note: str | None = None
    created_at: str


class ContextEntry(BaseModel):
    id: str
    category: str
    title: str
    content: str
    pinned: bool = False
    active: bool = True
    conflicts_with: list[str] = Field(default_factory=list)
    provenance: EntryProvenance
    superseded_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextRepoVersion(BaseModel):
    schema_version: Literal["JarvisContextRepoV1"] = SCHEMA_VERSION
    agent_id: str
    version: int
    created_at: str
    parent_version: int | None = None
    entries: list[ContextEntry] = Field(default_factory=list)


class AgentRepoMeta(BaseModel):
    agent_id: str
    current_version: int
    created_at: str
    updated_at: str


class MutationRecord(BaseModel):
    mutation_id: str
    agent_id: str
    version_before: int
    version_after: int
    action: str
    entry_id: str | None = None
    source: EntryProvenance
    before: ContextEntry | None = None
    after: ContextEntry | None = None
    reversible: bool = True
    reverted_by: str | None = None
    created_at: str


class VersionDiff(BaseModel):
    agent_id: str
    from_version: int
    to_version: int
    added: list[ContextEntry] = Field(default_factory=list)
    removed: list[ContextEntry] = Field(default_factory=list)
    changed: list[dict[str, Any]] = Field(default_factory=list)
    conflicts_flagged: list[str] = Field(default_factory=list)
