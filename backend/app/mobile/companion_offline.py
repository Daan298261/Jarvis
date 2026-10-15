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

# Minimal-refusal phone packs (RFC-0204 §2.1). URLs pin the Hugging Face commit so
# the SHA-256/size below always describe the bytes served. qwen35 needs llama.cpp
# >= v0.6.0 in the companion APK.
_HERETIC_2B_REV = "c166d9f30a342a379bbe3299aef938834654e1aa"
_URL_HERETIC_2B = (
    f"https://huggingface.co/jordanwoodson/Qwen3.5-2B-heretic-GGUF/resolve/{_HERETIC_2B_REV}/"
    "Qwen3.5-2B-heretic-Q4_K_M.gguf"
)
_ABLITERATED_4B_REV = "f3b61227dde75c72d12391c443efd6fa0229e0eb"
_URL_ABLITERATED_4B = (
    f"https://huggingface.co/mradermacher/Qwen3.5-4B-abliterated-GGUF/resolve/{_ABLITERATED_4B_REV}/"
    "Qwen3.5-4B-abliterated.Q4_K_M.gguf"
)

RECOMMENDED_PACK_ID = "qwen3-1.7b-abliterated-q4"

# Pinned allowlist — weights live under data/companion-packs/ (gitignored).
COMPANION_PACK_CATALOG: list[dict[str, Any]] = [
    {"id": RECOMMENDED_PACK_ID, "label": "Qwen3 1.7B Abliterated (Q4_K_M)",
     "filename": "Qwen3-1.7B-abliterated.Q4_K_M.gguf", "size_bytes": 1_107_409_024,
     "min_ram_mb": 2048, "context_tokens": 2048, "license": "apache-2.0", "recommended": True,
     "sha256": "6fb5977ef935e2a54c0bd5ec45e841d5ba4256b2223c25b4f707553abac8f448",
     "url": "https://huggingface.co/mradermacher/Qwen3-1.7B-abliterated-GGUF/resolve/ef85d5f367b9b49842f0ab88faf07e35d6dfa505/Qwen3-1.7B-abliterated.Q4_K_M.gguf"},
    {"id": "qwen3-1.7b-abliterated-q3", "label": "Qwen3 1.7B Abliterated — smaller download (Q3_K_M)",
     "filename": "Qwen3-1.7B-abliterated.Q3_K_M.gguf", "size_bytes": 939_538_560,
     "min_ram_mb": 1792, "context_tokens": 2048, "license": "apache-2.0", "recommended": False,
     "sha256": "3968be1d143c0a1c333887b0cb7d62b9a3d41848eb941c620f38c379e06a1388",
     "url": "https://huggingface.co/mradermacher/Qwen3-1.7B-abliterated-GGUF/resolve/ef85d5f367b9b49842f0ab88faf07e35d6dfa505/Qwen3-1.7B-abliterated.Q3_K_M.gguf"},
    {"id": "qwen3-0.6b-abliterated-q4", "label": "Qwen3 0.6B Abliterated — low memory (Q4_K_M)",
     "filename": "Qwen3-0.6B-abliterated.Q4_K_M.gguf", "size_bytes": 396_704_896,
     "min_ram_mb": 1024, "context_tokens": 4096, "license": "apache-2.0", "recommended": False,
     "sha256": "405ecd904c83015cabaf2f30a8ecb52b5d71711752a78a363f7abad5fa1b5c97",
     "url": "https://huggingface.co/mradermacher/Qwen3-0.6B-abliterated-GGUF/resolve/6447ed9befe9b70c34ed0af5f4706b9c11f6342a/Qwen3-0.6B-abliterated.Q4_K_M.gguf"},
    {
        "id": "qwen3.5-2b-heretic-q4",
        "label": "Qwen3.5 2B Heretic — minimal refusals (Q4_K_M)",
        "filename": "Qwen3.5-2B-heretic-Q4_K_M.gguf",
        "size_bytes": 1_270_807_936,
        "min_ram_mb": 2560,
        "context_tokens": 4096,
        "sha256": "dad8a69dddcd64f2221dd06ae5c46baceb31ed9bd0dec330306d77762c377cf1",
        "url": _URL_HERETIC_2B,
        "license": "apache-2.0",
        "recommended": False,
    },
    {
        "id": "qwen3.5-4b-abliterated-q4",
        "label": "Qwen3.5 4B Abliterated — opt-in, needs ~4.5 GB free RAM (8 GB+ phones) (Q4_K_M)",
        "filename": "Qwen3.5-4B-abliterated.Q4_K_M.gguf",
        "size_bytes": 2_707_514_688,
        "min_ram_mb": 4608,
        "context_tokens": 4096,
        "sha256": "1ec0b30c75b49223c82542caf2635a7af4edcda80d8c89759cc000d3871bf48e",
        "url": _URL_ABLITERATED_4B,
        "license": "apache-2.0",
        "recommended": False,
    },
    {
        "id": "qwen2.5-1.5b-instruct-q4",
        "label": "Qwen2.5 1.5B Instruct (Q4_K_M)",
        "filename": "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        "size_bytes": 1_117_320_736,
        "min_ram_mb": 3072,
        "context_tokens": 2048,
        "sha256": "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        "url": _URL_15B,
        "recommended": False,
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
    from ..inference.lmstudio_catalog import resolved_cache_dir

    local = data_dir() / "companion-packs"
    dest = resolved_cache_dir(
        "companion-packs",
        local=local,
        markers=tuple(str(pack["filename"]) for pack in COMPANION_PACK_CATALOG),
        need_bytes=2 * 1024**3,
    )
    dest.mkdir(parents=True, exist_ok=True)
    return dest


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


def _verified_marker_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".verified")


def _write_verified_marker(path: Path, digest: str) -> None:
    marker = _verified_marker_path(path)
    try:
        marker.write_text(
            json.dumps({"sha256": digest.lower(), "size_bytes": path.stat().st_size}),
            encoding="utf-8",
        )
    except OSError:
        log.debug("Could not write companion pack verified marker for %s", path, exc_info=True)


def _marker_matches(path: Path, expected: str) -> bool:
    marker = _verified_marker_path(path)
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if str(payload.get("sha256") or "").lower() != expected.lower():
            return False
        return int(payload.get("size_bytes") or -1) == path.stat().st_size
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _cache_ready(pack: dict[str, Any]) -> bool:
    """True when the pack file exists at the expected size and has been verified.

    Full SHA-256 of a ~1GB GGUF must not run on every /api/companion/models poll —
    that stalls the asyncio event loop. After the first successful verify we trust a
    sidecar marker until size or expected digest changes.
    """
    path = pack_cache_path(pack)
    expected = (pack.get("sha256") or "").lower()
    if not expected or set(expected) == {"0"}:
        return False
    try:
        if not path.is_file():
            return False
        size = path.stat().st_size
        if size <= 0:
            return False
        expected_size = int(pack.get("size_bytes") or 0)
        if expected_size > 0 and size != expected_size:
            return False
        if _marker_matches(path, expected):
            return True
        # Incomplete downloads stay as .partial; a full-size file without a marker
        # still needs one hash (off hot path when possible).
        return False
    except OSError:
        return False


def _verify_and_mark(path: Path, expected: str) -> bool:
    digest = _sha256_file(path).lower()
    if digest != expected.lower():
        return False
    _write_verified_marker(path, digest)
    return True


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
    recommended = pack_by_id(RECOMMENDED_PACK_ID)
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
    pack = pack_by_id(RECOMMENDED_PACK_ID)
    if not pack:
        return
    if _cache_ready(pack):
        _CACHE.update(state="ready", pack_id=pack["id"], bytes_done=pack["size_bytes"], size_bytes=pack["size_bytes"], last_error="")
        return
    target = pack_cache_path(pack)
    expected = str(pack.get("sha256") or "").lower()
    expected_size = int(pack.get("size_bytes") or 0)
    # One-time off-loop verify for an already-complete file that lacks a marker.
    if target.is_file() and expected and (expected_size <= 0 or target.stat().st_size == expected_size):
        ok = await asyncio.to_thread(_verify_and_mark, target, expected)
        if ok:
            _CACHE.update(
                state="ready",
                pack_id=pack["id"],
                bytes_done=expected_size or target.stat().st_size,
                size_bytes=expected_size or target.stat().st_size,
                last_error="",
            )
            return
    partial = pack_partial_path(pack)
    size_bytes = int(pack["size_bytes"])
    _CACHE.update(state="downloading", pack_id=pack["id"], bytes_done=partial.stat().st_size if partial.is_file() else 0,
                  size_bytes=size_bytes, last_error="")
    headers: dict[str, str] = {}
    resume_at = partial.stat().st_size if partial.is_file() else 0
    if resume_at > 0:
        headers["Range"] = f"bytes={resume_at}-"
    try:
        from ..policy.network_http import gated_stream

        async with gated_stream(
            pack["url"],
            tool="web_fetch",
            timeout=httpx.Timeout(30.0, read=300.0),
            headers=headers,
        ) as response:
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
                    # Yield so health/task routes stay responsive during multi-GB cache.
                    await asyncio.sleep(0)
        expected = str(pack["sha256"]).lower()
        ok = await asyncio.to_thread(_verify_and_mark, partial, expected)
        if not ok:
            partial.unlink(missing_ok=True)
            _verified_marker_path(partial).unlink(missing_ok=True)
            raise RuntimeError("Downloaded pack failed SHA-256 verification")
        partial.replace(target)
        # Move marker with the final filename.
        partial_marker = _verified_marker_path(partial)
        final_marker = _verified_marker_path(target)
        if partial_marker.is_file():
            partial_marker.replace(final_marker)
        else:
            _write_verified_marker(target, expected)
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
