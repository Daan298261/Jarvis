"""RFC-0132 Supermemory configuration, health, search, and native sync API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config as app_config
from ..licensing.inference import InferenceCredentialError, upsert_inference_credential
from ..memory.repository import get_repo
from ..memory.supermemory import (
    SUPERMEMORY_PROVIDER,
    SupermemoryError,
    probe,
    resolve_status,
    search,
    sync_repo,
    validate_base_url,
)

router = APIRouter(prefix="/api/supermemory", tags=["supermemory"])


class SupermemoryConfigIn(BaseModel):
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=500)
    container_prefix: str | None = Field(default=None, min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    timeout_ms: int | None = Field(default=None, ge=100, le=10000)
    max_results: int | None = Field(default=None, ge=1, le=10)
    minimum_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    mirror_writes: bool | None = None
    allow_remote: bool | None = None


class CredentialIn(BaseModel):
    secret: str = Field(min_length=1, max_length=4000)
    label: str = Field(default="Supermemory", max_length=120)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    agent_id: str = Field(default="owner", min_length=1, max_length=120)
    limit: int | None = Field(default=None, ge=1, le=10)


@router.get("")
async def supermemory_status() -> dict[str, Any]:
    return resolve_status()


@router.put("")
async def configure_supermemory(body: SupermemoryConfigIn) -> dict[str, Any]:
    settings = app_config.load_settings()
    values = settings.supermemory.model_dump()
    updates = body.model_dump(exclude_none=True)
    values.update(updates)
    try:
        validate_base_url(str(values["base_url"]), allow_remote=bool(values["allow_remote"]))
        settings.supermemory = type(settings.supermemory).model_validate(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    app_config.save_settings(settings)
    return resolve_status()


@router.post("/credentials")
async def bind_supermemory_key(body: CredentialIn) -> dict[str, Any]:
    settings = app_config.load_settings().supermemory
    try:
        record = upsert_inference_credential(
            provider=SUPERMEMORY_PROVIDER,
            label=body.label or "Supermemory",
            secret=body.secret,
            endpoint=settings.base_url,
        )
    except InferenceCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "credential": {"id": record.get("id"), "provider": record.get("provider"), "label": record.get("label")},
        "status": resolve_status(),
    }


@router.post("/probe")
async def probe_supermemory() -> dict[str, Any]:
    return await probe()


@router.post("/search")
async def search_supermemory(body: SearchIn) -> dict[str, Any]:
    try:
        hits = await search(body.agent_id, body.query, limit=body.limit)
    except SupermemoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "agent_id": body.agent_id,
        "query": body.query,
        "hits": [
            {"id": hit.id, "text": hit.text, "similarity": hit.similarity, "metadata": hit.metadata}
            for hit in hits
        ],
    }


@router.post("/sync/{agent_id}")
async def sync_context_repo(agent_id: str) -> dict[str, Any]:
    repo = await get_repo(agent_id)
    result = await sync_repo(agent_id, repo.entries)
    return {"agent_id": agent_id, "version": repo.version, **result}
