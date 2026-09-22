from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from ..projects import portal_store

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectLinkIn(BaseModel):
    link_type: Literal["task", "owner_chat", "repo"]
    link_id: str = Field(min_length=1, max_length=1024)


class LocalImportIn(BaseModel):
    projects: list[dict[str, Any]] = Field(default_factory=list)


@router.get("")
async def get_projects() -> dict[str, Any]:
    return {"projects": await portal_store.list_projects()}


@router.post("")
async def post_project(body: ProjectCreateIn) -> dict[str, Any]:
    return await portal_store.create_project(body.name)


@router.patch("/{project_id}")
async def patch_project(project_id: str, body: ProjectRenameIn) -> dict[str, Any]:
    await portal_store.rename_project(project_id, body.name)
    return {"ok": True, "id": project_id, "name": body.name.strip()}


@router.delete("/{project_id}")
async def remove_project(project_id: str) -> dict[str, Any]:
    await portal_store.delete_project(project_id)
    return {"ok": True}


@router.post("/{project_id}/links")
async def add_link(project_id: str, body: ProjectLinkIn) -> dict[str, Any]:
    await portal_store.link_member(project_id, body.link_type, body.link_id)
    return {"ok": True}


@router.delete("/links/{link_type}/{link_id:path}")
async def remove_link(link_type: str, link_id: str) -> dict[str, Any]:
    if link_type not in {"task", "owner_chat", "repo"}:
        raise HTTPException(400, "Invalid link_type")
    await portal_store.unlink_member(link_type, link_id)
    return {"ok": True}


@router.delete("/unlink")
async def remove_link_query(link_type: str, link_id: str) -> dict[str, Any]:
    if link_type not in {"task", "owner_chat", "repo"}:
        raise HTTPException(400, "Invalid link_type")
    await portal_store.unlink_member(link_type, link_id)
    return {"ok": True}


@router.post("/import-local")
async def import_local(body: LocalImportIn) -> dict[str, Any]:
    count = await portal_store.import_local_projects(body.projects)
    return {"imported": count, "projects": await portal_store.list_projects()}


@router.get("/conversations/{conversation_id}")
async def open_conversation(conversation_id: str) -> dict[str, Any]:
    detail = await portal_store.open_conversation(conversation_id)
    if not detail:
        raise HTTPException(404, "Conversation not found")
    return detail
