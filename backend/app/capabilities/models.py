"""Pydantic models for the RFC-0137 capability registry."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ParityState = Literal["missing", "partial", "equivalent"]
LifecycleState = Literal["specified", "implemented", "verified", "parity_demonstrated"]
SupportMode = Literal["local", "cloud", "offline", "hybrid", "n/a"]


class PeerEvidence(BaseModel):
    label: str = ""
    url: str = ""
    observed_at: str = ""


class CapabilityRecord(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    title: str
    rfc_id: str = ""
    user_outcome: str = ""
    anzu_path: str = ""
    parity_state: ParityState = "missing"
    lifecycle: LifecycleState = "specified"
    support: SupportMode = "local"
    security_approval: str = ""
    test_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    peer_evidence: list[PeerEvidence] = Field(default_factory=list)
    license_note: str = ""
    last_verified_at: str = ""


class CapabilityRegistry(BaseModel):
    version: int = 1
    updated_at: str = ""
    capabilities: list[CapabilityRecord] = Field(default_factory=list)
