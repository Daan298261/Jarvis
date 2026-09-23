"""RFC-0140: companion on-device STT/TTS voice pack catalog and Leader cache."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import HTTPException

from ..config import data_dir

log = logging.getLogger(__name__)

PackCacheState = Literal["idle", "downloading", "ready", "error"]

_URL_WHISPER_TINY = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin"
)
_URL_WHISPER_BASE = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
)
_URL_PIPER_ONNX = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
    "en/en_US/lessac/medium/en_US-lessac-medium.onnx"
)
_URL_PIPER_JSON = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
    "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
)
_POCKET_BASE = (
    "https://huggingface.co/soniqo/Pocket-TTS-100M-ONNX-INT8/resolve/v1.0.0"
)

# Pinned allowlist — weights under data/companion-voice-packs/ (gitignored). Empty url is a fail.
COMPANION_VOICE_PACK_CATALOG: list[dict[str, Any]] = [
    {
        "id": "whisper-tiny-en-cpp",
        "role": "stt",
        "label": "Whisper tiny.en (whisper.cpp)",
        "engine": "whisper.cpp",
        "filename": "ggml-tiny.en.bin",
        "size_bytes": 77_704_715,
        "min_ram_mb": 512,
        "sha256": "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f",
        "url": _URL_WHISPER_TINY,
        "recommended": True,
        "artifacts": [
            {
                "filename": "ggml-tiny.en.bin",
                "url": _URL_WHISPER_TINY,
                "sha256": "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f",
                "size_bytes": 77_704_715,
            }
        ],
    },
    {
        "id": "whisper-base-en-cpp",
        "role": "stt",
        "label": "Whisper base.en (whisper.cpp)",
        "engine": "whisper.cpp",
        "filename": "ggml-base.en.bin",
        "size_bytes": 147_964_211,
        "min_ram_mb": 1024,
        "sha256": "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002",
        "url": _URL_WHISPER_BASE,
        "recommended": False,
        "artifacts": [
            {
                "filename": "ggml-base.en.bin",
                "url": _URL_WHISPER_BASE,
                "sha256": "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002",
                "size_bytes": 147_964_211,
            }
        ],
    },
    {
        "id": "pocket-tts-en",
        "role": "tts",
        "label": "Pocket TTS English (ONNX INT8 / Alba)",
        "engine": "pocket-tts-onnx",
        "filename": "pocket-tts-en",
        "size_bytes": 126_155_593,
        "min_ram_mb": 768,
        "sha256": "1e50e05031f8711ab0cb10aac0953432c604104e76180ec4b6f7cc4393746e08",
        "url": f"{_POCKET_BASE}/lm_main.int8.onnx",
        "recommended": True,
        "artifacts": [
            {
                "filename": "decoder.int8.onnx",
                "url": f"{_POCKET_BASE}/decoder.int8.onnx",
                "sha256": "ed8d050fc5da275cfca88224b7d2cc29fde7c23e133618f346e98ac505b3d862",
                "size_bytes": 22_695_710,
            },
            {
                "filename": "encoder.onnx",
                "url": f"{_POCKET_BASE}/encoder.onnx",
                "sha256": "2194513df47271ece9f8d2d571facd57b24d96a1d912fdc13bf0e10c69318e85",
                "size_bytes": 512_407,
            },
            {
                "filename": "lm_flow.int8.onnx",
                "url": f"{_POCKET_BASE}/lm_flow.int8.onnx",
                "sha256": "8d627d235c44a597da908e1085ebe241cbbe358964c502c5a5063d18851a5529",
                "size_bytes": 9_962_530,
            },
            {
                "filename": "lm_main.int8.onnx",
                "url": f"{_POCKET_BASE}/lm_main.int8.onnx",
                "sha256": "bfc0c7e7e3d72864fa3bb2ee499f62f21ddc1474b885f5f3ca570f8be73e787e",
                "size_bytes": 76_341_079,
            },
            {
                "filename": "manifest.json",
                "url": f"{_POCKET_BASE}/manifest.json",
                "sha256": "5eeff5278cfb1e9b627d972512ddf1e2dfacf61827103d9fb9c53707b38d0968",
                "size_bytes": 2_934,
            },
            {
                "filename": "text_conditioner.onnx",
                "url": f"{_POCKET_BASE}/text_conditioner.onnx",
                "sha256": "5217b8474621af91127cfef891714337ae8cba106710ce04a426ec4bd56bbd1e",
                "size_bytes": 16_388_498,
            },
            {
                "filename": "token_scores.json",
                "url": f"{_POCKET_BASE}/token_scores.json",
                "sha256": "3baa6ef7d57bac245271e33f96161f3ac60038d753f13f3fdbe24a7d2422ad6b",
                "size_bytes": 123_617,
            },
            {
                "filename": "tokenizer.model",
                "url": f"{_POCKET_BASE}/tokenizer.model",
                "sha256": "d461765ae179566678c93091c5fa6f2984c31bbe990bf1aa62d92c64d91bc3f6",
                "size_bytes": 59_339,
            },
            {
                "filename": "vocab.json",
                "url": f"{_POCKET_BASE}/vocab.json",
                "sha256": "a2673c232cf49dd6eb1ad850e7c7682f6443c2ab64040d1150e9d8f2a7e3587b",
                "size_bytes": 69_479,
            },
        ],
    },
    {
        "id": "piper-en-lessac-medium",
        "role": "tts",
        "label": "Piper en_US lessac medium",
        "engine": "piper-onnx",
        "filename": "en_US-lessac-medium.onnx",
        "size_bytes": 63_206_179,
        "min_ram_mb": 384,
        "sha256": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
        "url": _URL_PIPER_ONNX,
        "recommended": False,
        "artifacts": [
            {
                "filename": "en_US-lessac-medium.onnx",
                "url": _URL_PIPER_ONNX,
                "sha256": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
                "size_bytes": 63_201_294,
            },
            {
                "filename": "en_US-lessac-medium.onnx.json",
                "url": _URL_PIPER_JSON,
                "sha256": "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0",
                "size_bytes": 4_885,
            },
        ],
    },
]

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

# Combined recommended STT+TTS must stay under hard auto-download gate without owner confirm.
_AUTO_DOWNLOAD_HARD_CAP_BYTES = 500_000_000


def voice_pack_cache_dir() -> Path:
    path = data_dir() / "companion-voice-packs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def voice_pack_by_id(pack_id: str) -> dict[str, Any] | None:
    for pack in COMPANION_VOICE_PACK_CATALOG:
        if pack["id"] == pack_id:
            return pack
    return None


def recommended_voice_packs() -> list[dict[str, Any]]:
    return [p for p in COMPANION_VOICE_PACK_CATALOG if p.get("recommended")]


def pack_artifacts(pack: dict[str, Any]) -> list[dict[str, Any]]:
    arts = pack.get("artifacts")
    if arts:
        return list(arts)
    return [
        {
            "filename": pack["filename"],
            "url": pack["url"],
            "sha256": pack["sha256"],
            "size_bytes": pack["size_bytes"],
        }
    ]


def pack_cache_root(pack: dict[str, Any]) -> Path:
    return voice_pack_cache_dir() / pack["id"]


def artifact_cache_path(pack: dict[str, Any], artifact: dict[str, Any]) -> Path:
    return pack_cache_root(pack) / artifact["filename"]


def artifact_partial_path(pack: dict[str, Any], artifact: dict[str, Any]) -> Path:
    return pack_cache_root(pack) / f"{artifact['filename']}.partial"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_catalog_urls() -> None:
    """Empty URL rows are a hard fail (RFC-0140)."""
    for pack in COMPANION_VOICE_PACK_CATALOG:
        if not (pack.get("url") or "").strip():
            raise ValueError(f"Voice pack {pack.get('id')} has empty url")
        for art in pack_artifacts(pack):
            if not (art.get("url") or "").strip():
                raise ValueError(f"Voice pack {pack.get('id')} artifact {art.get('filename')} has empty url")
            sha = (art.get("sha256") or "").lower()
            if not sha or set(sha) == {"0"} or len(sha) != 64:
                raise ValueError(f"Voice pack {pack.get('id')} artifact {art.get('filename')} missing real sha256")


def _artifact_ready(pack: dict[str, Any], artifact: dict[str, Any]) -> bool:
    path = artifact_cache_path(pack, artifact)
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    expected = (artifact.get("sha256") or "").lower()
    if not expected or set(expected) == {"0"}:
        return False
    try:
        return _sha256_file(path).lower() == expected
    except OSError:
        return False


def _cache_ready(pack: dict[str, Any]) -> bool:
    return all(_artifact_ready(pack, art) for art in pack_artifacts(pack))


def leader_voice_cache_status(pack_id: str | None = None) -> dict[str, Any]:
    pack = voice_pack_by_id(pack_id) if pack_id else None
    if pack is None and pack_id:
        return {
            "state": "error",
            "pack_id": pack_id,
            "bytes_done": 0,
            "size_bytes": 0,
            "last_error": "Unknown voice pack",
        }
    if pack is None:
        pack = next((p for p in COMPANION_VOICE_PACK_CATALOG if p.get("recommended") and p.get("role") == "stt"), None)
        if pack is None:
            return {"state": "idle", "pack_id": "", "bytes_done": 0, "size_bytes": 0, "last_error": ""}
    size_bytes = int(pack["size_bytes"])
    if _cache_ready(pack):
        return {
            "state": "ready",
            "pack_id": pack["id"],
            "bytes_done": size_bytes,
            "size_bytes": size_bytes,
            "last_error": "",
        }
    bytes_done = 0
    for art in pack_artifacts(pack):
        partial = artifact_partial_path(pack, art)
        final = artifact_cache_path(pack, art)
        if final.is_file():
            bytes_done += final.stat().st_size
        elif partial.is_file():
            bytes_done += partial.stat().st_size
    state = _CACHE.get("state", "idle")
    if state == "downloading" and _CACHE.get("pack_id") == pack["id"]:
        bytes_done = max(bytes_done, int(_CACHE.get("bytes_done", 0)))
    return {
        "state": state if state != "ready" else ("ready" if _cache_ready(pack) else state),
        "pack_id": pack["id"],
        "bytes_done": bytes_done,
        "size_bytes": size_bytes,
        "last_error": _CACHE.get("last_error", "") if _CACHE.get("pack_id") == pack["id"] else "",
    }


def voice_pack_catalog() -> dict[str, Any]:
    validate_catalog_urls()
    packs: list[dict[str, Any]] = []
    for entry in COMPANION_VOICE_PACK_CATALOG:
        item = dict(entry)
        item["leader_cache"] = leader_voice_cache_status(entry["id"])
        item["leader_cached"] = item["leader_cache"]["state"] == "ready"
        packs.append(item)
    recommended = recommended_voice_packs()
    combined = sum(int(p["size_bytes"]) for p in recommended)
    return {
        "catalog_version": 1,
        "stt_engine": "whisper.cpp",
        "tts_engine": "pocket-tts-onnx|piper-onnx",
        "packs": packs,
        "recommended_combined_bytes": combined,
        "auto_download_hard_cap_bytes": _AUTO_DOWNLOAD_HARD_CAP_BYTES,
        "leader_voice_pack_cache": {
            p["id"]: leader_voice_cache_status(p["id"]) for p in recommended
        },
        "note": (
            "Pinned HTTPS URLs for on-device STT/TTS (RFC-0140). "
            "Online sessions still prefer Leader/Kokoro; packs are Mode A/B fallback."
        ),
    }


def resolve_voice_pack_artifact(pack_id: str, filename: str | None = None) -> Path:
    pack = voice_pack_by_id(pack_id)
    if not pack:
        raise HTTPException(404, "Unknown companion voice pack")
    if not _cache_ready(pack):
        raise HTTPException(409, "Voice pack is not cached on this Leader yet")
    arts = pack_artifacts(pack)
    if filename:
        for art in arts:
            if art["filename"] == filename:
                path = artifact_cache_path(pack, art)
                if not path.is_file():
                    raise HTTPException(409, "Voice pack artifact is unavailable")
                return path
        raise HTTPException(404, "Unknown voice pack artifact")
    # Single-file convenience: primary artifact
    primary = arts[0]
    path = artifact_cache_path(pack, primary)
    if not path.is_file():
        raise HTTPException(409, "Voice pack file is unavailable")
    if len(arts) > 1:
        # Multi-file packs must request a specific artifact name.
        raise HTTPException(
            400,
            f"Pack {pack_id} has multiple artifacts; request /voice-packs/{pack_id}/file/{{filename}}",
        )
    return path


async def _download_artifact(client: httpx.AsyncClient, pack: dict[str, Any], artifact: dict[str, Any]) -> None:
    target = artifact_cache_path(pack, artifact)
    partial = artifact_partial_path(pack, artifact)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _artifact_ready(pack, artifact):
        return
    headers: dict[str, str] = {}
    resume_at = partial.stat().st_size if partial.is_file() else 0
    if resume_at > 0:
        headers["Range"] = f"bytes={resume_at}-"
    async with client.stream("GET", artifact["url"], headers=headers) as response:
        if response.status_code not in {200, 206}:
            raise RuntimeError(f"Download failed with status {response.status_code} for {artifact['filename']}")
        mode = "ab" if resume_at > 0 and response.status_code == 206 else "wb"
        if mode == "wb":
            resume_at = 0
            partial.unlink(missing_ok=True)
        with partial.open(mode) as handle:
            async for chunk in response.aiter_bytes(1024 * 1024):
                handle.write(chunk)
                resume_at += len(chunk)
                _CACHE["bytes_done"] = int(_CACHE.get("bytes_done", 0)) + len(chunk)
    digest = _sha256_file(partial).lower()
    if digest != artifact["sha256"].lower():
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded {artifact['filename']} failed SHA-256 verification")
    partial.replace(target)


async def _download_recommended_voice_packs() -> None:
    validate_catalog_urls()
    packs = recommended_voice_packs()
    combined = sum(int(p["size_bytes"]) for p in packs)
    if combined > _AUTO_DOWNLOAD_HARD_CAP_BYTES:
        _CACHE.update(
            state="error",
            last_error=f"Recommended voice packs ({combined} bytes) exceed auto-download hard cap",
        )
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as client:
        for pack in packs:
            if _cache_ready(pack):
                continue
            size_bytes = int(pack["size_bytes"])
            _CACHE.update(
                state="downloading",
                pack_id=pack["id"],
                bytes_done=0,
                size_bytes=size_bytes,
                last_error="",
            )
            try:
                for art in pack_artifacts(pack):
                    await _download_artifact(client, pack, art)
                if not _cache_ready(pack):
                    raise RuntimeError("Voice pack incomplete after download")
                _CACHE.update(state="ready", bytes_done=size_bytes, last_error="")
            except Exception as exc:
                log.warning("Companion voice pack cache download failed for %s: %s", pack["id"], exc)
                _CACHE.update(state="error", pack_id=pack["id"], last_error=str(exc)[:500])
                return


async def ensure_recommended_voice_pack_cache() -> None:
    global _DOWNLOAD_TASK
    async with _DOWNLOAD_LOCK:
        if _DOWNLOAD_TASK and not _DOWNLOAD_TASK.done():
            return
        _DOWNLOAD_TASK = asyncio.create_task(_download_recommended_voice_packs())


def start_recommended_voice_pack_cache() -> None:
    """Non-blocking first-up background fetch of recommended STT+TTS packs."""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    try:
        validate_catalog_urls()
    except ValueError as exc:
        log.error("Companion voice pack catalog invalid: %s", exc)
        _CACHE.update(state="error", last_error=str(exc))
        return
    packs = recommended_voice_packs()
    if packs and all(_cache_ready(p) for p in packs):
        _CACHE.update(
            state="ready",
            pack_id=packs[0]["id"],
            bytes_done=sum(int(p["size_bytes"]) for p in packs),
            size_bytes=sum(int(p["size_bytes"]) for p in packs),
            last_error="",
        )
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(ensure_recommended_voice_pack_cache())
