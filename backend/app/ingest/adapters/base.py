from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..schema import ExternalContentArtifact


@dataclass
class IngestContext:
    url: str
    platform: str
    provider_url: str = ""
    headless: bool = True
    tiers_attempted: list[str] = field(default_factory=list)


class PlatformAdapter(Protocol):
    platform: str

    async def resolve_http(self, ctx: IngestContext) -> ExternalContentArtifact | None: ...

    async def resolve_provider(self, ctx: IngestContext) -> ExternalContentArtifact | None: ...
