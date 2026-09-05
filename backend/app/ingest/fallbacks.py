from __future__ import annotations

import json
import re

from .adapters.base import IngestContext
from .links import extract_urls
from .schema import ExternalContentArtifact

_OG_TAG = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?P<key>[^"\']+)["\'][^>]+content=["\'](?P<value>[^"\']+)["\']',
    re.I,
)


def _parse_meta_from_snapshot(snapshot: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for match in _OG_TAG.finditer(snapshot or ""):
        tags[match.group("key").lower()] = match.group("value")
    return tags


async def extract_with_browser(ctx: IngestContext, browser_tool) -> ExternalContentArtifact | None:
    opened = await browser_tool.execute(action="open", url=ctx.url, headless=ctx.headless)
    if not opened.success:
        return None
    evaluated = await browser_tool.execute(
        action="evaluate",
        script=(
            "() => {"
            "const metas = Array.from(document.querySelectorAll('meta'));"
            "const data = {};"
            "for (const meta of metas) {"
            "  const key = meta.getAttribute('property') || meta.getAttribute('name');"
            "  const value = meta.getAttribute('content');"
            "  if (key && value) data[key] = value;"
            "}"
            "const imgs = Array.from(document.querySelectorAll('img[src]')).map(i => i.src).slice(0, 12);"
            "const videos = Array.from(document.querySelectorAll('video[src], source[src]')).map(v => v.src).slice(0, 6);"
            "return JSON.stringify({"
            "  title: document.title,"
            "  text: document.body ? document.body.innerText.slice(0, 8000) : '',"
            "  metas: data,"
            "  images: imgs,"
            "  videos: videos"
            "});"
            "}"
        ),
        headless=ctx.headless,
    )
    if not evaluated.success:
        snapshot = await browser_tool.execute(action="snapshot", headless=ctx.headless)
        if not snapshot.success:
            return None
        tags = _parse_meta_from_snapshot(snapshot.output)
        title = tags.get("og:title") or ""
        caption = tags.get("og:description") or ""
        images = [tags[k] for k in ("og:image", "twitter:image") if tags.get(k)]
        text = "\n".join(part for part in (title, caption, snapshot.output[:4000]) if part)
        links = extract_urls(caption, text)
        return ExternalContentArtifact(
            source=ctx.platform,
            url=ctx.url,
            author=tags.get("og:site_name") or "",
            title=title,
            caption=caption,
            text=text,
            images=images,
            video=[tags["og:video"]] if tags.get("og:video") else [],
            links=links,
            metadata={"tier": "browser", "mode": "snapshot"},
        )

    try:
        payload = json.loads(evaluated.output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    metas = payload.get("metas") if isinstance(payload.get("metas"), dict) else {}
    title = str(payload.get("title") or metas.get("og:title") or "")
    caption = str(metas.get("og:description") or metas.get("description") or "")
    text = str(payload.get("text") or caption or title)
    images = [str(item) for item in (payload.get("images") or []) if item]
    if not images:
        images = [metas[k] for k in ("og:image", "twitter:image") if metas.get(k)]
    videos = [str(item) for item in (payload.get("videos") or []) if item]
    if metas.get("og:video") and metas["og:video"] not in videos:
        videos.append(str(metas["og:video"]))
    links = extract_urls(caption, text, *images)
    return ExternalContentArtifact(
        source=ctx.platform,
        url=ctx.url,
        author=str(metas.get("og:site_name") or ""),
        title=title,
        caption=caption,
        text=text,
        images=images,
        video=videos,
        links=links,
        metadata={"tier": "browser", "mode": "evaluate"},
    )


async def extract_with_browser_use(ctx: IngestContext, browser_use_tool) -> ExternalContentArtifact | None:
    goal = (
        "Extract the post title, author, caption/text, all image URLs, and video URLs from this page. "
        "Return plain text only."
    )
    result = await browser_use_tool.execute(goal=goal, url=ctx.url)
    if not result.success:
        return None
    text = (result.output or "").strip()
    if not text:
        return None
    links = extract_urls(text)
    images = [url for url in links if any(ext in url.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", "cdninstagram"))]
    videos = [url for url in links if any(ext in url.lower() for ext in (".mp4", ".webm", "video"))]
    other_links = [url for url in links if url not in images and url not in videos]
    return ExternalContentArtifact(
        source=ctx.platform,
        url=ctx.url,
        author="",
        title="",
        caption=text[:500],
        text=text,
        images=images,
        video=videos,
        links=other_links,
        metadata={"tier": "browser_use"},
    )
