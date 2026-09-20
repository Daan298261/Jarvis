"""RFC-0132: bounded Supermemory recall with authoritative native fallback."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .. import config as app_config
from ..licensing.inference import get_secret_by_provider
from .schema import ContextEntry

SUPERMEMORY_PROVIDER = "supermemory"
UPSTREAM_REPOSITORY = "https://github.com/supermemoryai/supermemory"
UPSTREAM_RELEASE = "server-v0.0.8"


class SupermemoryError(RuntimeError):
    pass


class SupermemoryNotConfigured(SupermemoryError):
    pass


@dataclass(frozen=True)
class SemanticMemoryHit:
    id: str
    text: str
    similarity: float
    metadata: dict[str, Any]


def _api_key() -> str:
    return (os.environ.get("JARVIS_SUPERMEMORY_API_KEY") or get_secret_by_provider(SUPERMEMORY_PROVIDER)).strip()


def _is_loopback_host(host: str | None) -> bool:
    cleaned = (host or "").strip().lower().strip("[]")
    if cleaned == "localhost":
        return True
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except ValueError:
        return False


def validate_base_url(base_url: str, *, allow_remote: bool) -> str:
    cleaned = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Supermemory base_url must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Supermemory base_url must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("Supermemory base_url must not contain an API path")
    if not allow_remote and not _is_loopback_host(parsed.hostname):
        raise ValueError("Remote Supermemory endpoints require allow_remote=true")
    return cleaned


def container_tag(agent_id: str, *, prefix: str | None = None) -> str:
    settings = app_config.load_settings().supermemory
    head = prefix or settings.container_prefix
    tail = re.sub(r"[^A-Za-z0-9_-]+", "_", str(agent_id or "owner")).strip("_") or "owner"
    return f"{head}_{tail}"[:100]


def custom_id(agent_id: str, entry_id: str) -> str:
    raw = f"jarvis_{agent_id}_{entry_id}"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw)[:100]


def resolve_status() -> dict[str, Any]:
    settings = app_config.load_settings().supermemory
    endpoint_error = ""
    try:
        endpoint = validate_base_url(settings.base_url, allow_remote=settings.allow_remote)
    except ValueError as exc:
        endpoint = ""
        endpoint_error = str(exc)
    key_bound = bool(_api_key())
    configured = bool(settings.enabled and endpoint and key_bound)
    binary = Path(app_config.repo_root()) / "runtime" / "supermemory" / "supermemory-server.exe"
    return {
        "enabled": settings.enabled,
        "configured": configured,
        "base_url": endpoint or settings.base_url,
        "endpoint_error": endpoint_error,
        "key_bound": key_bound,
        "loopback": bool(endpoint and _is_loopback_host(urlparse(endpoint).hostname)),
        "allow_remote": settings.allow_remote,
        "container_prefix": settings.container_prefix,
        "timeout_ms": settings.timeout_ms,
        "max_results": settings.max_results,
        "minimum_similarity": settings.minimum_similarity,
        "mirror_writes": settings.mirror_writes,
        "native_fallback": True,
        "fallback_store": "jarvis_context_repo",
        "authoritative_store": "jarvis_context_repo",
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_release": UPSTREAM_RELEASE,
        "server_installed": binary.is_file(),
    }


async def _request_json(method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = app_config.load_settings().supermemory
    if not settings.enabled:
        raise SupermemoryNotConfigured("Supermemory is disabled")
    try:
        base_url = validate_base_url(settings.base_url, allow_remote=settings.allow_remote)
    except ValueError as exc:
        raise SupermemoryNotConfigured(str(exc)) from exc
    key = _api_key()
    if not key:
        raise SupermemoryNotConfigured("Supermemory API key is not configured")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=settings.timeout_ms / 1000.0, trust_env=False) as client:
            response = await client.request(method, f"{base_url}{path}", headers=headers, json=payload)
            response.raise_for_status()
            data = {"ok": True} if response.status_code == 204 or not response.content else response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SupermemoryError(f"Supermemory request failed: {exc}") from exc
    if not isinstance(data, dict):
        raise SupermemoryError("Supermemory returned a non-object response")
    return data


async def search(agent_id: str, query: str, *, limit: int | None = None) -> list[SemanticMemoryHit]:
    settings = app_config.load_settings().supermemory
    cleaned = str(query or "").strip()
    if not cleaned:
        return []
    wanted = max(1, min(limit or settings.max_results, settings.max_results, 10))
    payload = {
        "q": cleaned,
        "containerTag": container_tag(agent_id, prefix=settings.container_prefix),
        "searchMode": "hybrid",
        "limit": wanted,
        "threshold": settings.minimum_similarity,
        "rerank": False,
        "rewriteQuery": False,
    }
    data = await _request_json("POST", "/v4/search", payload=payload)
    rows = data.get("results")
    if not isinstance(rows, list):
        raise SupermemoryError("Supermemory search response has no results list")
    hits: list[SemanticMemoryHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("memory") or row.get("chunk") or row.get("content") or "").strip()
        if not text:
            continue
        try:
            similarity = float(row.get("similarity") or 0.0)
        except (TypeError, ValueError):
            similarity = 0.0
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        hits.append(
            SemanticMemoryHit(
                id=str(row.get("id") or "unknown")[:160],
                text=text,
                similarity=max(0.0, min(similarity, 1.0)),
                metadata=dict(metadata),
            )
        )
        if len(hits) >= wanted:
            break
    return hits


async def probe() -> dict[str, Any]:
    try:
        await search("probe", "Jarvis Supermemory connectivity probe", limit=1)
    except SupermemoryError as exc:
        return {**resolve_status(), "ok": False, "error": str(exc)[:400]}
    return {**resolve_status(), "ok": True, "error": ""}


def _entry_document(entry: ContextEntry) -> str:
    return f"[{entry.category}] {entry.title}\n\n{entry.content}".strip()


async def mirror_entry(agent_id: str, entry: ContextEntry) -> dict[str, Any] | None:
    settings = app_config.load_settings().supermemory
    if not settings.enabled or not settings.mirror_writes or not entry.active:
        return None
    return await _request_json(
        "POST",
        "/v3/documents",
        payload={
            "content": _entry_document(entry),
            "containerTag": container_tag(agent_id, prefix=settings.container_prefix),
            "customId": custom_id(agent_id, entry.id),
            "taskType": "superrag",
            "metadata": {
                "source": "jarvis_context_repo",
                "agent_id": agent_id,
                "entry_id": entry.id,
                "category": entry.category,
                "pinned": entry.pinned,
            },
        },
    )


async def forget_entry(agent_id: str, entry_id: str) -> dict[str, Any] | None:
    settings = app_config.load_settings().supermemory
    if not settings.enabled or not settings.mirror_writes:
        return None
    return await _request_json("DELETE", f"/v3/documents/{quote(custom_id(agent_id, entry_id), safe='')}")


async def mirror_mutation(agent_id: str, *, action: str, before: ContextEntry | None, after: ContextEntry | None) -> None:
    """Best-effort mirror. Native mutation has already committed when called."""
    try:
        if after is not None and after.active:
            await mirror_entry(agent_id, after)
        elif before is not None and action in {"delete", "revert"}:
            await forget_entry(agent_id, before.id)
    except SupermemoryError:
        logging.warning("Supermemory mirror failed; native ContextRepo remains authoritative", exc_info=True)


async def sync_repo(agent_id: str, entries: list[ContextEntry]) -> dict[str, int]:
    queued = 0
    failed = 0
    for entry in entries:
        if not entry.active:
            continue
        try:
            result = await mirror_entry(agent_id, entry)
            if result is not None:
                queued += 1
        except SupermemoryError:
            failed += 1
    return {"queued": queued, "failed": failed, "total": queued + failed}
