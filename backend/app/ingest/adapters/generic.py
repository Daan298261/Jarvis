from __future__ import annotations

import re
from html import unescape
from typing import Any

import httpx

from ..links import extract_urls
from ..schema import ExternalContentArtifact
from .base import IngestContext

_OG_TAG = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?P<key>[^"\']+)["\'][^>]+content=["\'](?P<value>[^"\']+)["\']',
    re.I,
)
_OG_TAG_REV = re.compile(
    r'<meta[^>]+content=["\'](?P<value>[^"\']+)["\'][^>]+(?:property|name)=["\'](?P<key>[^"\']+)["\']',
    re.I,
)


def _parse_og_tags(html: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for pattern in (_OG_TAG, _OG_TAG_REV):
        for match in pattern.finditer(html or ""):
            tags[match.group("key").lower()] = unescape(match.group("value"))
    return tags


def _collect_images(tags: dict[str, str], extra: list[str] | None = None) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()
    for key in ("og:image", "og:image:url", "twitter:image"):
        value = tags.get(key)
        if value and value not in seen:
            seen.add(value)
            images.append(value)
    for item in extra or []:
        if item and item not in seen:
            seen.add(item)
            images.append(item)
    return images


def _artifact_from_tags(
    *,
    source: str,
    url: str,
    tags: dict[str, str],
    images: list[str] | None = None,
    videos: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExternalContentArtifact:
    title = tags.get("og:title") or tags.get("twitter:title") or ""
    caption = tags.get("og:description") or tags.get("description") or tags.get("twitter:description") or ""
    author = tags.get("og:site_name") or tags.get("author") or ""
    text = "\n".join(part for part in (title, caption) if part).strip()
    all_images = _collect_images(tags, images)
    all_videos = list(videos or [])
    if tags.get("og:video"):
        all_videos.append(tags["og:video"])
    links = extract_urls(caption, text)
    return ExternalContentArtifact(
        source=source,
        url=url,
        author=author,
        title=title,
        caption=caption,
        text=text,
        images=all_images,
        video=all_videos,
        links=links,
        metadata=metadata or {},
    )


async def _fetch_html(url: str, timeout: float = 20.0) -> str:
    headers = {"User-Agent": "JarvisLocal/1.0"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


class GenericWebAdapter:
    platform = "web"

    async def resolve_http(self, ctx: IngestContext) -> ExternalContentArtifact | None:
        try:
            html = await _fetch_html(ctx.url)
        except Exception:
            return None
        tags = _parse_og_tags(html)
        if not tags and not html.strip():
            return None
        return _artifact_from_tags(source=ctx.platform, url=ctx.url, tags=tags, metadata={"tier": "http"})

    async def resolve_provider(self, ctx: IngestContext) -> ExternalContentArtifact | None:
        if not ctx.provider_url:
            return None
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
                response = await client.get(ctx.provider_url, params={"url": ctx.url})
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        images = payload.get("images") or payload.get("image") or []
        if isinstance(images, str):
            images = [images]
        videos = payload.get("video") or payload.get("videos") or []
        if isinstance(videos, str):
            videos = [videos]
        caption = str(payload.get("caption") or payload.get("description") or "")
        title = str(payload.get("title") or "")
        text = str(payload.get("text") or caption or title)
        links = extract_urls(caption, text, *images, *videos)
        return ExternalContentArtifact(
            source=ctx.platform,
            url=ctx.url,
            author=str(payload.get("author") or payload.get("username") or ""),
            title=title,
            caption=caption,
            text=text,
            images=[str(item) for item in images if item],
            video=[str(item) for item in videos if item],
            links=links,
            metadata={"tier": "provider", "provider": ctx.provider_url},
        )
