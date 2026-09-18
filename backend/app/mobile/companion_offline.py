"""RFC-0108: companion on-device model pack catalog and offline turn sync."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select

from ..db.models import Conversation
from ..db.session import SessionLocal

# Pinned allowlist — weights are never stored on the Leader; URLs/hashes only.
COMPANION_PACK_CATALOG: list[dict[str, Any]] = [
    {
        "id": "qwen2.5-1.5b-instruct-q4",
        "label": "Qwen2.5 1.5B Instruct (Q4_K_M)",
        "filename": "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        "size_bytes": 1_050_000_000,
        "min_ram_mb": 3072,
        "context_tokens": 2048,
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "url": "",
        "recommended": True,
    },
    {
        "id": "qwen2.5-3b-instruct-q4",
        "label": "Qwen2.5 3B Instruct (Q4_K_M)",
        "filename": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "size_bytes": 2_100_000_000,
        "min_ram_mb": 5120,
        "context_tokens": 2048,
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "url": "",
        "recommended": False,
    },
]

DeviceOrigin = Literal["leader", "device_offline", "device_local_draft"]


def pack_catalog() -> dict[str, Any]:
    return {
        "catalog_version": 1,
        "engine": "llama.cpp",
        "packs": COMPANION_PACK_CATALOG,
        "note": "Download packs on the phone; Leader never hosts GGUF weights for companion inference.",
    }


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
