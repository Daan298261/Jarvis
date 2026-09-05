from __future__ import annotations

from typing import Any

from .adapters import adapter_for
from .adapters.base import IngestContext
from .fallbacks import extract_with_browser, extract_with_browser_use
from .hooks import finalize_artifact, provider_url_for
from .platform import detect_platform
from .schema import ExternalContentArtifact


class IngestError(Exception):
    def __init__(self, message: str, *, tiers_attempted: list[str]) -> None:
        super().__init__(message)
        self.tiers_attempted = tiers_attempted


async def ingest_url(
    url: str,
    *,
    web_fetch_tool=None,
    browser_tool=None,
    browser_use_tool=None,
    headless: bool | None = None,
) -> dict[str, Any]:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("url is required")

    platform = detect_platform(cleaned)
    ctx = IngestContext(
        url=cleaned,
        platform=platform,
        provider_url=provider_url_for(platform),
        headless=headless if headless is not None else True,
    )
    adapter = adapter_for(platform)
    tiers = ("http", "provider", "browser", "browser_use")

    artifact: ExternalContentArtifact | None = None
    for tier in tiers:
        ctx.tiers_attempted.append(tier)
        try:
            if tier == "http":
                artifact = await adapter.resolve_http(ctx)
            elif tier == "provider":
                artifact = await adapter.resolve_provider(ctx)
            elif tier == "browser":
                if browser_tool is None:
                    continue
                artifact = await extract_with_browser(ctx, browser_tool)
            elif tier == "browser_use":
                if browser_use_tool is None:
                    continue
                artifact = await extract_with_browser_use(ctx, browser_use_tool)
        except Exception:
            artifact = None
        if artifact is not None:
            break

    if artifact is None:
        raise IngestError(
            f"Could not ingest content from {cleaned}",
            tiers_attempted=ctx.tiers_attempted,
        )

    return finalize_artifact(artifact, ctx.tiers_attempted)
