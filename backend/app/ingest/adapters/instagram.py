from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

import httpx

from ..links import extract_urls
from ..schema import ExternalContentArtifact
from .base import IngestContext
from .generic import GenericWebAdapter, _collect_images, _fetch_html, _parse_og_tags

_JSON_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<body>.*?)</script>', re.I | re.S)


def _parse_instagram_json(html: str) -> dict[str, Any] | None:
    for pattern in (
        re.compile(r"window\._sharedData\s*=\s*(?P<body>\{.*?\});", re.S),
        re.compile(r"window\.__additionalDataLoaded\([^,]+,\s*(?P<body>\{.*?\})\s*\);", re.S),
    ):
        match = pattern.search(html or "")
        if match:
            try:
                return json.loads(match.group("body"))
            except json.JSONDecodeError:
                continue
    for match in _JSON_LD.finditer(html or ""):
        try:
            payload = json.loads(match.group("body"))
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue
    return None


def _instagram_media_from_payload(payload: dict[str, Any]) -> tuple[list[str], list[str], str, str, str]:
    images: list[str] = []
    videos: list[str] = []
    caption = ""
    author = ""
    title = ""

    def walk(node: Any) -> None:
        nonlocal caption, author, title
        if isinstance(node, dict):
            if node.get("__typename") in {"GraphImage", "GraphVideo", "XDTGraphImage", "XDTGraphVideo"}:
                if node.get("display_url"):
                    images.append(str(node["display_url"]))
                if node.get("video_url"):
                    videos.append(str(node["video_url"]))
            edges = node.get("edge_sidecar_to_children", {}).get("edges")
            if isinstance(edges, list):
                for edge in edges:
                    child = edge.get("node") if isinstance(edge, dict) else None
                    if isinstance(child, dict):
                        if child.get("display_url"):
                            images.append(str(child["display_url"]))
                        if child.get("video_url"):
                            videos.append(str(child["video_url"]))
            for key in ("edge_media_to_caption", "caption"):
                block = node.get(key)
                if isinstance(block, dict):
                    edge_edges = block.get("edges")
                    if isinstance(edge_edges, list) and edge_edges:
                        node_text = edge_edges[0].get("node", {}).get("text")
                        if node_text:
                            caption = str(node_text)
                elif isinstance(block, str):
                    caption = block
            if node.get("username"):
                author = str(node["username"])
            if node.get("title"):
                title = str(node["title"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return list(dict.fromkeys(images)), list(dict.fromkeys(videos)), caption, author, title


class InstagramAdapter:
    platform = "instagram"

    async def resolve_http(self, ctx: IngestContext) -> ExternalContentArtifact | None:
        oembed_url = "https://api.instagram.com/oembed"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
                response = await client.get(oembed_url, params={"url": ctx.url})
                if response.is_success:
                    payload = response.json()
                    if isinstance(payload, dict):
                        title = str(payload.get("title") or payload.get("author_name") or "")
                        author = str(payload.get("author_name") or "")
                        thumbnail = str(payload.get("thumbnail_url") or "")
                        html = str(payload.get("html") or "")
                        images = [thumbnail] if thumbnail else []
                        links = extract_urls(html, title)
                        return ExternalContentArtifact(
                            source="instagram",
                            url=ctx.url,
                            author=author,
                            title=title,
                            caption=title,
                            text=title,
                            images=images,
                            video=[],
                            links=links,
                            metadata={"tier": "http", "resolver": "oembed"},
                        )
        except Exception:
            pass

        try:
            html = await _fetch_html(ctx.url)
        except Exception:
            return None

        payload = _parse_instagram_json(html)
        images: list[str] = []
        videos: list[str] = []
        caption = ""
        author = ""
        title = ""
        if payload:
            images, videos, caption, author, title = _instagram_media_from_payload(payload)

        tags = _parse_og_tags(html)
        if not title:
            title = tags.get("og:title") or ""
        if not caption:
            caption = tags.get("og:description") or tags.get("description") or ""
        if not author:
            author = tags.get("og:site_name") or ""
        if not images:
            images = _collect_images(tags)
        if not videos and tags.get("og:video"):
            videos = [tags["og:video"]]

        if not any((title, caption, images, videos)):
            return None

        text = "\n".join(part for part in (title, caption) if part).strip()
        links = extract_urls(caption, text, *images)
        return ExternalContentArtifact(
            source="instagram",
            url=ctx.url,
            author=author,
            title=title,
            caption=caption,
            text=text,
            images=images,
            video=videos,
            links=links,
            metadata={"tier": "http", "resolver": "html"},
        )

    async def resolve_provider(self, ctx: IngestContext) -> ExternalContentArtifact | None:
        return await GenericWebAdapter().resolve_provider(ctx)
