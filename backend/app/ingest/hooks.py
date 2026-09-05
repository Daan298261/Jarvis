from __future__ import annotations

import os
from typing import Any

from .links import extract_repo_urls
from .redaction import redact_artifact
from .schema import ExternalContentArtifact


def research_hooks(artifact: ExternalContentArtifact) -> dict[str, Any]:
    """Lightweight downstream hook — surfaces repo URLs for research/vision agents."""
    repo_urls = extract_repo_urls(artifact.caption, artifact.text, *artifact.links)
    return {
        "repo_urls": repo_urls,
        "media_count": len(artifact.images) + len(artifact.video),
        "link_count": len(artifact.links),
        "vision_candidates": artifact.images[:8],
    }


def provider_url_for(platform: str) -> str:
    env_key = f"JARVIS_INGEST_PROVIDER_{platform.upper()}"
    return (os.environ.get(env_key) or os.environ.get("JARVIS_INGEST_PROVIDER_URL") or "").strip()


def finalize_artifact(artifact: ExternalContentArtifact, tiers_attempted: list[str]) -> dict[str, Any]:
    payload = artifact.to_dict()
    payload["metadata"] = {
        **(artifact.metadata or {}),
        "tiers_attempted": tiers_attempted,
    }
    payload["links"] = list(dict.fromkeys(payload.get("links") or []))
    cleaned = redact_artifact(payload)
    cleaned["research"] = research_hooks(artifact)
    return cleaned
