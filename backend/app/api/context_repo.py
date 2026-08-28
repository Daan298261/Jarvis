from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..memory import (
    ContextRepoError,
    add_entry,
    consolidate_agent,
    delete_entry,
    diff_versions,
    get_entry,
    get_entry_permissions,
    get_repo,
    get_version,
    list_history,
    list_versions,
    pin_entry,
    rank_nodes_for_consolidation,
    revert_mutation,
)
from ..swarm.nodes import list_nodes

router = APIRouter(prefix="/api/context-repo", tags=["context-repo"])


class EntryIn(BaseModel):
    category: str
    title: str
    content: str
    source_type: str = "manual"
    source_id: str | None = None
    trajectory_id: str | None = None
    note: str | None = None


class ConsolidateIn(BaseModel):
    agent_id: str
    trajectory_ids: list[str] = Field(default_factory=list)


class PinIn(BaseModel):
    pinned: bool = True


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ContextRepoError):
        status = 409 if "Duplicate" in str(exc) or "already reverted" in str(exc) else 400
        return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/consolidate")
async def run_consolidation(body: ConsolidateIn):
    trajectory_ids = set(body.trajectory_ids) if body.trajectory_ids else None
    return await consolidate_agent(body.agent_id, trajectory_ids=trajectory_ids)


@router.get("/consolidate/schedule-preference")
async def consolidation_schedule_preference():
    nodes = await list_nodes()
    ranked = rank_nodes_for_consolidation(nodes)
    return {"nodes": ranked, "preferred": [item for item in ranked if item.get("preferred")]}


@router.get("/{agent_id}")
async def inspect_repo(agent_id: str):
    repo = await get_repo(agent_id)
    return repo.model_dump(mode="json")


@router.get("/{agent_id}/versions")
async def repo_versions(agent_id: str):
    return await list_versions(agent_id)


@router.get("/{agent_id}/versions/{version}")
async def repo_version(agent_id: str, version: int):
    repo = await get_version(agent_id, version)
    if repo is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return repo.model_dump(mode="json")


@router.get("/{agent_id}/diff")
async def repo_diff(agent_id: str, from_version: int, to_version: int):
    try:
        diff = await diff_versions(agent_id, from_version, to_version)
    except ContextRepoError as exc:
        raise _http_error(exc) from exc
    return diff.model_dump(mode="json")


@router.get("/{agent_id}/history")
async def repo_history(agent_id: str, limit: int = 100):
    records = await list_history(agent_id, limit=limit)
    return [record.model_dump(mode="json") for record in records]


@router.get("/{agent_id}/entries/{entry_id}")
async def inspect_entry(agent_id: str, entry_id: str):
    entry = await get_entry(agent_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    permissions = await get_entry_permissions(agent_id, entry_id)
    payload = entry.model_dump(mode="json")
    payload["permissions"] = permissions
    return payload


@router.post("/{agent_id}/entries")
async def create_entry(agent_id: str, body: EntryIn):
    try:
        entry, repo, mutation = await add_entry(
            agent_id,
            category=body.category,
            title=body.title,
            content=body.content,
            source_type=body.source_type,
            source_id=body.source_id,
            trajectory_id=body.trajectory_id,
            note=body.note,
        )
    except ContextRepoError as exc:
        raise _http_error(exc) from exc
    return {
        "entry": entry.model_dump(mode="json"),
        "version": repo.version,
        "mutation_id": mutation.mutation_id,
    }


@router.post("/{agent_id}/entries/{entry_id}/pin")
async def pin_repo_entry(agent_id: str, entry_id: str, body: PinIn | None = None):
    body = body or PinIn()
    try:
        entry = await pin_entry(agent_id, entry_id, pinned=body.pinned)
    except ContextRepoError as exc:
        raise _http_error(exc) from exc
    return entry.model_dump(mode="json")


@router.delete("/{agent_id}/entries/{entry_id}")
async def remove_entry(agent_id: str, entry_id: str):
    try:
        entry = await delete_entry(agent_id, entry_id)
    except ContextRepoError as exc:
        raise _http_error(exc) from exc
    return entry.model_dump(mode="json")


@router.post("/{agent_id}/revert/{mutation_id}")
async def revert_repo_mutation(agent_id: str, mutation_id: str):
    try:
        repo = await revert_mutation(agent_id, mutation_id)
    except ContextRepoError as exc:
        raise _http_error(exc) from exc
    return repo.model_dump(mode="json")
