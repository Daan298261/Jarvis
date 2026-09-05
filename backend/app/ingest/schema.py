from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExternalContentArtifact(BaseModel):
    source: str
    url: str
    author: str = ""
    title: str = ""
    caption: str = ""
    text: str = ""
    images: list[str] = Field(default_factory=list)
    video: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
