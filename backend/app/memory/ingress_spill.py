"""RFC-0122: Authoritative DB store for oversized owner ingress payloads."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select

from ..db.models import IngressBlob, utcnow
from ..db.session import SessionLocal
from ..inference.prompt_budget import estimate_text_tokens

CHUNK_BODY_LIMIT = 48_000
PREVIEW_CHARS = 480


def content_hash(text: str) -> str:
    normalized = (text or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK_BODY_LIMIT:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + CHUNK_BODY_LIMIT])
        start += CHUNK_BODY_LIMIT
    return chunks


async def store_ingress_blob(
    *,
    body: str,
    conversation_id: str = "",
    task_id: str = "",
    mime: str = "text/plain",
) -> IngressBlob:
    text = body or ""
    byte_size = len(text.encode("utf-8"))
    token_estimate = estimate_text_tokens(text)
    digest = content_hash(text)
    blob_id = str(uuid.uuid4())
    chunks = _chunk_text(text)
    async with SessionLocal() as session:
        for index, chunk in enumerate(chunks):
            row = IngressBlob(
                id=blob_id if index == 0 else f"{blob_id}#{index}",
                root_id=blob_id,
                conversation_id=conversation_id or task_id,
                task_id=task_id,
                chunk_index=index,
                byte_size=byte_size,
                token_estimate=token_estimate,
                content_hash=digest,
                mime=mime,
                body=chunk,
                status="stored",
            )
            session.add(row)
        await session.commit()
        primary = await session.get(IngressBlob, blob_id)
        assert primary is not None
        return primary


async def get_ingress_blob(blob_id: str) -> IngressBlob | None:
    async with SessionLocal() as session:
        return await session.get(IngressBlob, blob_id)


async def list_ingress_chunks(blob_id: str) -> list[IngressBlob]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(IngressBlob)
                .where(IngressBlob.root_id == blob_id)
                .order_by(IngressBlob.chunk_index.asc())
            )
        ).scalars().all()
        if rows:
            return list(rows)
        single = await session.get(IngressBlob, blob_id)
        return [single] if single else []


async def read_ingress(blob_id: str, offset: int = 0, limit: int = CHUNK_BODY_LIMIT) -> str:
    chunks = await list_ingress_chunks(blob_id)
    if not chunks:
        return ""
    combined = "".join(row.body or "" for row in chunks)
    start = max(0, int(offset))
    end = start + max(1, int(limit))
    return combined[start:end]


def preview_for_gate(blob: IngressBlob | None, full_text: str) -> str:
    text = full_text or ""
    if blob is not None:
        text = blob.body or text
    if len(text) <= PREVIEW_CHARS:
        return text
    half = PREVIEW_CHARS // 2
    return f"{text[:half]}\n…\n{text[-half:]}"


def spill_metadata_dict(blob: IngressBlob) -> dict[str, Any]:
    return {
        "blob_id": blob.root_id or blob.id,
        "byte_size": blob.byte_size,
        "token_estimate": blob.token_estimate,
        "content_hash": blob.content_hash,
        "mime": blob.mime,
        "chunk_count": 1,
    }


async def spill_metadata(blob_id: str) -> dict[str, Any]:
    chunks = await list_ingress_chunks(blob_id)
    if not chunks:
        return {}
    head = chunks[0]
    return {
        "blob_id": head.root_id or head.id,
        "byte_size": head.byte_size,
        "token_estimate": head.token_estimate,
        "content_hash": head.content_hash,
        "mime": head.mime,
        "chunk_count": len(chunks),
    }


async def mark_vault_spilled(blob_id: str) -> None:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(IngressBlob).where(IngressBlob.root_id == blob_id))
        ).scalars().all()
        for row in rows:
            row.status = "spilled_to_vault"
            row.updated_at = utcnow()
        await session.commit()


async def ingress_prompt_segment(blob_id: str, ask: str, *, max_chars: int = 6000) -> str:
    """Bounded segment for the major model working set."""
    segment = await read_ingress(blob_id, 0, max_chars)
    if not segment:
        return ""
    meta = await spill_metadata(blob_id)
    return (
        f"Stored owner ingress ({meta.get('byte_size', 0)} bytes, id={blob_id}). "
        f"Read only this segment for the current ask; the remainder stays in DB.\n"
        f"Current ask: {ask[:400]}\n\n"
        f"--- ingress segment ---\n{segment}\n--- end segment ---"
    )


async def maybe_mirror_to_vault(blob_id: str, ask: str, body_preview: str) -> bool:
    """Best-effort RFC-0107 durable mirror; unbound vault does not block."""
    from .obsidian_vault import public_binding_status, write_decision_to_vault

    if not public_binding_status().get("bound"):
        return False
    durable_markers = (
        "rfc",
        "spec",
        "architecture",
        "requirements",
        "stack trace",
        "error log",
        "project",
    )
    hay = f"{ask} {body_preview}".lower()
    if not any(marker in hay for marker in durable_markers):
        return False
    try:
        title = (ask or "Owner ingress").strip()[:80] or "Owner ingress"
        await write_decision_to_vault(
            title,
            f"RFC-0122 ingress mirror\n\nblob_id: {blob_id}\n\n{body_preview[:4000]}",
            memory_id=blob_id,
            subdir="_Temporal/Sessions",
        )
        await mark_vault_spilled(blob_id)
        return True
    except Exception:
        return False
