"""RFC-0108: companion on-device model pack catalog, Leader cache, and offline turn sync."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from ..config import data_dir
from ..db.models import Conversation
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

PackCacheState = Literal["idle", "downloading", "ready", "error"]

_URL_15B = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-1.5b-instruct-q4_k_m.gguf"
)
_URL_3B = (
    "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/"
    "qwen2.5-3b-instruct-q4_k_m.gguf"
)

# Pinned allowlist — weights live under data/companion-packs/ (gitignored).
COMPANION_PACK_CATALOG: list[dict[str, Any]] = [
    {
        "id": "qwen2.5-1.5b-instruct-q4",
        "label": "Qwen2.5 1.5B Instruct (Q4_K_M)",
        "filename": "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        "size_bytes": 1_117_320_736,
        "min_ram_mb": 3072,
        "context_tokens": 2048,
        "sha256": "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        "url": _URL_15B,
        "recommended": True,
    },
    {
        "id": "qwen2.5-3b-instruct-q4",
        "label": "Qwen2.5 3B Instruct (Q4_K_M)",
        "filename": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "size_bytes": 2_104_932_768,
        "min_ram_mb": 5120,
        "context_tokens": 2048,
        "sha256": "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d",
        "url": _URL_3B,
        "recommended": False,
    },
]

DeviceOrigin = Literal["leader", "device_offline", "device_local_draft"]

_CACHE: dict[str, Any] = {
    "state": "idle",
    "pack_id": "",
    "bytes_done": 0,
    "size_bytes": 0,
    "last_error": "",
}
_DOWNLOAD_LOCK = asyncio.Lock()
_DOWNLOAD_TASK: asyncio.Task | None = None
_STARTED = False


def pack_cache_dir() -> Path:
    path = data_dir() / "companion-packs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pack_by_id(pack_id: str) -> dict[str, Any] | None:
    for pack in COMPANION_PACK_CATALOG:
        if pack["id"] == pack_id:
            return pack
    return None


def pack_cache_path(pack: dict[str, Any]) -> Path:
    return pack_cache_dir() / pack["filename"]


def pack_partial_path(pack: dict[str, Any]) -> Path:
    return pack_cache_dir() / f"{pack['filename']}.partial"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_ready(pack: dict[str, Any]) -> bool:
    path = pack_cache_path(pack)
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    expected = (pack.get("sha256") or "").lower()
    if not expected or set(expected) == {"0"}:
        return False
    try:
        return _sha256_file(path).lower() == expected
    except OSError:
        return False


def leader_cache_status(pack_id: str | None = None) -> dict[str, Any]:
    pack = pack_by_id(pack_id or "qwen2.5-1.5b-instruct-q4")
    if not pack:
        return {"state": "error", "pack_id": pack_id or "", "bytes_done": 0, "size_bytes": 0, "last_error": "Unknown pack"}
    size_bytes = int(pack["size_bytes"])
    if _cache_ready(pack):
        return {
            "state": "ready",
            "pack_id": pack["id"],
            "bytes_done": size_bytes,
            "size_bytes": size_bytes,
            "last_error": "",
        }
    partial = pack_partial_path(pack)
    bytes_done = partial.stat().st_size if partial.is_file() else 0
    state = _CACHE.get("state", "idle")
    if state == "downloading" and _CACHE.get("pack_id") == pack["id"]:
        bytes_done = max(bytes_done, int(_CACHE.get("bytes_done", 0)))
    return {
        "state": state if state != "ready" else ("ready" if _cache_ready(pack) else state),
        "pack_id": pack["id"],
        "bytes_done": bytes_done,
        "size_bytes": size_bytes,
        "last_error": _CACHE.get("last_error", ""),
    }


def pack_catalog() -> dict[str, Any]:
    packs: list[dict[str, Any]] = []
    for entry in COMPANION_PACK_CATALOG:
        item = dict(entry)
        item["leader_cache"] = leader_cache_status(entry["id"])
        item["leader_cached"] = item["leader_cache"]["state"] == "ready"
        packs.append(item)
    recommended = pack_by_id("qwen2.5-1.5b-instruct-q4")
    cache = leader_cache_status(recommended["id"]) if recommended else _CACHE
    return {
        "catalog_version": 1,
        "engine": "llama.cpp",
        "packs": packs,
        "leader_pack_cache": cache,
        "note": "Pinned HTTPS URLs; Leader caches the recommended pack for paired download.",
    }


def resolve_pack_file(pack_id: str) -> Path:
    pack = pack_by_id(pack_id)
    if not pack:
        raise HTTPException(404, "Unknown companion model pack")
    if not _cache_ready(pack):
        raise HTTPException(409, "Pack is not cached on this Leader yet")
    path = pack_cache_path(pack)
    if not path.is_file():
        raise HTTPException(409, "Pack file is unavailable")
    return path


async def _download_recommended() -> None:
    pack = pack_by_id("qwen2.5-1.5b-instruct-q4")
    if not pack:
        return
    if _cache_ready(pack):
        _CACHE.update(state="ready", pack_id=pack["id"], bytes_done=pack["size_bytes"], size_bytes=pack["size_bytes"], last_error="")
        return
    target = pack_cache_path(pack)
    partial = pack_partial_path(pack)
    size_bytes = int(pack["size_bytes"])
    _CACHE.update(state="downloading", pack_id=pack["id"], bytes_done=partial.stat().st_size if partial.is_file() else 0,
                  size_bytes=size_bytes, last_error="")
    headers: dict[str, str] = {}
    resume_at = partial.stat().st_size if partial.is_file() else 0
    if resume_at > 0:
        headers["Range"] = f"bytes={resume_at}-"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as client:
            async with client.stream("GET", pack["url"], headers=headers) as response:
                if response.status_code not in {200, 206}:
                    raise RuntimeError(f"Download failed with status {response.status_code}")
                mode = "ab" if resume_at > 0 and response.status_code == 206 else "wb"
                if mode == "wb":
                    resume_at = 0
                    partial.unlink(missing_ok=True)
                with partial.open(mode) as handle:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        handle.write(chunk)
                        resume_at += len(chunk)
                        _CACHE["bytes_done"] = resume_at
        digest = _sha256_file(partial).lower()
        if digest != pack["sha256"].lower():
            partial.unlink(missing_ok=True)
            raise RuntimeError("Downloaded pack failed SHA-256 verification")
        partial.replace(target)
        _CACHE.update(state="ready", bytes_done=size_bytes, last_error="")
    except Exception as exc:
        log.warning("Companion pack cache download failed: %s", exc)
        _CACHE.update(state="error", last_error=str(exc)[:500])


async def ensure_recommended_pack_cache() -> None:
    global _DOWNLOAD_TASK
    async with _DOWNLOAD_LOCK:
        if _DOWNLOAD_TASK and not _DOWNLOAD_TASK.done():
            return
        _DOWNLOAD_TASK = asyncio.create_task(_download_recommended())


def start_recommended_pack_cache() -> None:
    """Non-blocking first-up background fetch of the recommended allowlisted pack."""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    pack = pack_by_id("qwen2.5-1.5b-instruct-q4")
    if pack and _cache_ready(pack):
        _CACHE.update(state="ready", pack_id=pack["id"], bytes_done=pack["size_bytes"], size_bytes=pack["size_bytes"], last_error="")
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(ensure_recommended_pack_cache())


def _validate_turn(turn: dict[str, Any]) -> dict[str, Any]:
    role = turn.get("role")
    if role not in {"user", "assistant"}:
        raise HTTPException(400, "Each turn must have role user or assistant")
    text = (turn.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Turn text is required")
    if len(text) > 32000:
        raise HTTPException(400, "Turn text exceeds 32 KiB")
    origin = turn.get("origin") or "device_offline"
    if origin not in {"device_offline", "device_local_draft", "leader"}:
        raise HTTPException(400, "Invalid turn origin")
    if role == "assistant" and origin != "device_local_draft":
        raise HTTPException(400, "Assistant offline turns must be device_local_draft until Leader accepts")
    if role == "user" and origin not in {"device_offline", "leader"}:
        raise HTTPException(400, "User offline turns must be device_offline")
    request_id = turn.get("request_id")
    try:
        request_uuid = uuid.UUID(str(request_id))
    except (TypeError, ValueError):
        raise HTTPException(400, "Each turn requires a stable request_id UUID")
    client_id = turn.get("client_message_id")
    try:
        client_uuid = uuid.UUID(str(client_id)) if client_id else request_uuid
    except (TypeError, ValueError):
        raise HTTPException(400, "client_message_id must be a UUID when provided")
    return {
        "id": str(client_uuid),
        "role": role,
        "text": text,
        "origin": origin,
        "request_id": str(request_uuid),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


async def sync_offline_turns(
    device_id: str,
    conversation_id: str | None,
    turns: list[dict[str, Any]],
) -> dict[str, Any]:
    if not turns:
        raise HTTPException(400, "At least one offline turn is required")
    if len(turns) > 50:
        raise HTTPException(400, "Too many turns in one sync batch")
    normalized = [_validate_turn(item) for item in turns]
    fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    cid = conversation_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis-offline:{device_id}:{fingerprint}"))
    async with SessionLocal() as db:
        conversation = await db.get(Conversation, cid)
        if conversation is None:
            title = next((t["text"][:100] for t in normalized if t["role"] == "user"), "Offline companion")
            conversation = Conversation(id=cid, title=title, messages_json="[]")
            db.add(conversation)
        messages = json.loads(conversation.messages_json)
        existing_ids = {m.get("id") for m in messages}
        appended = 0
        for turn in normalized:
            if turn["id"] in existing_ids:
                continue
            entry: dict[str, Any] = {
                "id": turn["id"],
                "role": turn["role"],
                "text": turn["text"],
                "origin": turn["origin"],
                "request_id": turn["request_id"],
                "device_id": device_id,
                "canonical": turn["origin"] == "leader",
            }
            if turn["role"] == "assistant" and turn["origin"] == "device_local_draft":
                entry["pending_leader_acceptance"] = True
            messages.append(entry)
            existing_ids.add(turn["id"])
            appended += 1
        conversation.messages_json = json.dumps(messages)
        conversation.updated_at = datetime.now(timezone.utc)
        await db.commit()
    return {
        "conversation_id": cid,
        "appended": appended,
        "leader_canonical": True,
        "sync_fingerprint": fingerprint,
    }
