"""RFC-0107 vault API — bind, search, act, health."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import load_settings, save_settings
from ..memory.obsidian_vault import (
    act_vault,
    bind_vault,
    public_binding_status,
    repair_vault_index,
    search_vault,
    unbind_vault,
    vault_health,
)

router = APIRouter(prefix="/api/vault", tags=["vault"])


class VaultBindIn(BaseModel):
    vault_path: str = Field(min_length=1)
    init_layout: bool = False


class VaultSearchIn(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=12, ge=1, le=50)


class VaultActIn(BaseModel):
    action: Literal["open", "read", "create", "append", "edit"]
    rel_path: str = ""
    content: str = ""
    query: str = ""
    force: bool = False


class VaultSyncIn(BaseModel):
    agent_id: str = "owner"
    query: str = Field(min_length=1)


@router.get("/status")
async def vault_status() -> dict[str, Any]:
    return public_binding_status()


@router.post("/bind")
async def vault_bind(body: VaultBindIn) -> dict[str, Any]:
    try:
        result = bind_vault(body.vault_path, init_layout=body.init_layout)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings = load_settings()
    settings.knowledge_vault.vault_path = body.vault_path.strip()
    settings.knowledge_vault.jarvis_managed_layout = body.init_layout
    save_settings(settings)
    return {**result, "status": public_binding_status()}


@router.post("/unbind")
async def vault_unbind() -> dict[str, Any]:
    result = unbind_vault()
    settings = load_settings()
    settings.knowledge_vault.vault_path = ""
    save_settings(settings)
    return result


@router.post("/search")
async def vault_search(body: VaultSearchIn) -> dict[str, Any]:
    hits = search_vault(body.query, limit=body.limit)
    return {
        "query": body.query,
        "hits": [
            {
                "rel_path": h.rel_path,
                "title": h.title,
                "heading": h.heading,
                "excerpt": h.excerpt,
                "content_hash": h.content_hash,
                "score": h.score,
            }
            for h in hits
        ],
    }


@router.post("/act")
async def vault_act(body: VaultActIn) -> dict[str, Any]:
    try:
        return act_vault(
            body.action,
            rel_path=body.rel_path,
            content=body.content,
            query=body.query,
            force=body.force,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health")
async def vault_health_endpoint() -> dict[str, Any]:
    health = vault_health()
    return {
        "binding": public_binding_status(),
        "broken_links": health.broken_links,
        "duplicate_ids": health.duplicate_ids,
        "stale_index_paths": health.stale_index_paths,
        "missing_router": health.missing_router,
    }


@router.post("/repair")
async def vault_repair() -> dict[str, Any]:
    return repair_vault_index()


@router.post("/sync/context-repo")
async def vault_sync_to_context_repo(body: VaultSyncIn) -> dict[str, Any]:
    from ..memory.obsidian_vault import sync_hit_to_context_repo

    hits = search_vault(body.query, limit=3)
    if not hits:
        return {"synced": 0, "entries": []}
    entries = []
    for hit in hits:
        entries.append(await sync_hit_to_context_repo(body.agent_id, hit))
    return {"synced": len(entries), "entries": entries}
