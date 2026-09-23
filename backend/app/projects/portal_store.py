from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import delete, select

from ..agent.compaction import serialize_messages
from ..db.models import Conversation, PortalProject, PortalProjectLink
from ..db.session import SessionLocal
from ..providers.base import ChatMessage
from .paths import project_media_dir


def _messages_from_json(raw: str) -> list[ChatMessage]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[ChatMessage] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        content = str(row.get("content") or "")
        if role in {"user", "assistant", "system"} and content:
            out.append(ChatMessage(role=role, content=content))
    return out


async def _require_project(session, project_id: str) -> PortalProject:
    row = await session.get(PortalProject, project_id)
    if row is None:
        raise LookupError(f"Project not found: {project_id}")
    return row


async def _set_owner_chat_project(session, conversation_id: str, project_id: str) -> None:
    row = await session.get(Conversation, conversation_id)
    if row is None:
        return
    row.project_id = project_id


async def _clear_owner_chat_project(session, conversation_id: str) -> None:
    row = await session.get(Conversation, conversation_id)
    if row is None:
        return
    row.project_id = ""


async def list_projects() -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(PortalProject).order_by(PortalProject.updated_at.desc()))).scalars().all()
        conv_rows = (
            await session.execute(
                select(Conversation).where(
                    Conversation.task_id == "",
                    Conversation.project_id != "",
                )
            )
        ).scalars().all()
        conv_by_project: dict[str, list[str]] = {}
        for conv in conv_rows:
            conv_by_project.setdefault(conv.project_id, []).append(conv.id)

        projects = []
        for row in rows:
            links = (
                await session.execute(
                    select(PortalProjectLink).where(PortalProjectLink.project_id == row.id)
                )
            ).scalars().all()
            task_ids = [link.link_id for link in links if link.link_type == "task"]
            chat_ids = list(dict.fromkeys(
                [link.link_id for link in links if link.link_type == "owner_chat"]
                + conv_by_project.get(row.id, [])
            ))
            repo_paths = [link.link_id for link in links if link.link_type == "repo"]
            projects.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "taskIds": task_ids,
                    "conversationIds": chat_ids,
                    "repoPaths": repo_paths,
                }
            )
        return projects


async def create_project(name: str) -> dict[str, Any]:
    pid = str(uuid.uuid4())
    async with SessionLocal() as session:
        session.add(PortalProject(id=pid, name=name.strip()))
        await session.commit()
    project_media_dir(pid)
    return {"id": pid, "name": name.strip(), "taskIds": [], "conversationIds": [], "repoPaths": []}


async def rename_project(project_id: str, name: str) -> None:
    async with SessionLocal() as session:
        row = await _require_project(session, project_id)
        row.name = name.strip()
        await session.commit()


async def delete_project(project_id: str) -> None:
    async with SessionLocal() as session:
        await _require_project(session, project_id)
        await session.execute(delete(PortalProjectLink).where(PortalProjectLink.project_id == project_id))
        conv_rows = (
            await session.execute(
                select(Conversation).where(Conversation.project_id == project_id)
            )
        ).scalars().all()
        for conv in conv_rows:
            conv.project_id = ""
        row = await session.get(PortalProject, project_id)
        if row:
            await session.delete(row)
        await session.commit()


async def link_member(project_id: str, link_type: str, link_id: str) -> None:
    async with SessionLocal() as session:
        await _require_project(session, project_id)
        await session.execute(
            delete(PortalProjectLink).where(
                PortalProjectLink.link_type == link_type,
                PortalProjectLink.link_id == link_id,
            )
        )
        session.add(
            PortalProjectLink(project_id=project_id, link_type=link_type, link_id=link_id)
        )
        if link_type == "owner_chat":
            await _set_owner_chat_project(session, link_id, project_id)
        await session.commit()


async def unlink_member(link_type: str, link_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(PortalProjectLink).where(
                PortalProjectLink.link_type == link_type,
                PortalProjectLink.link_id == link_id,
            )
        )
        if link_type == "owner_chat":
            await _clear_owner_chat_project(session, link_id)
        await session.commit()


async def import_local_projects(payload: list[dict[str, Any]]) -> int:
    """Best-effort migration from browser localStorage export."""
    imported = 0
    for row in payload:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        pid = str(row.get("id") or uuid.uuid4())
        async with SessionLocal() as session:
            existing = await session.get(PortalProject, pid)
            if existing is None:
                session.add(PortalProject(id=pid, name=name))
                project_media_dir(pid)
                imported += 1
            elif not existing.name.strip():
                existing.name = name

            for task_id in row.get("taskIds") or []:
                if not isinstance(task_id, str) or not task_id:
                    continue
                await session.execute(
                    delete(PortalProjectLink).where(
                        PortalProjectLink.link_type == "task",
                        PortalProjectLink.link_id == task_id,
                    )
                )
                session.add(PortalProjectLink(project_id=pid, link_type="task", link_id=task_id))

            for chat_id in row.get("conversationIds") or []:
                if not isinstance(chat_id, str) or not chat_id:
                    continue
                await session.execute(
                    delete(PortalProjectLink).where(
                        PortalProjectLink.link_type == "owner_chat",
                        PortalProjectLink.link_id == chat_id,
                    )
                )
                session.add(PortalProjectLink(project_id=pid, link_type="owner_chat", link_id=chat_id))
                await _set_owner_chat_project(session, chat_id, pid)

            for repo_path in row.get("repoPaths") or []:
                if not isinstance(repo_path, str) or not repo_path.strip():
                    continue
                path = repo_path.strip()
                await session.execute(
                    delete(PortalProjectLink).where(
                        PortalProjectLink.link_type == "repo",
                        PortalProjectLink.link_id == path,
                    )
                )
                session.add(PortalProjectLink(project_id=pid, link_type="repo", link_id=path))
            await session.commit()
    return imported


async def load_owner_conversation(conversation_id: str) -> list[ChatMessage]:
    async with SessionLocal() as session:
        row = await session.get(Conversation, conversation_id)
        if row is None:
            return []
        return _messages_from_json(row.messages_json)


async def save_owner_conversation(
    conversation_id: str,
    messages: list[ChatMessage],
    *,
    title: str = "",
    project_id: str = "",
) -> None:
    blob = serialize_messages(messages)
    async with SessionLocal() as session:
        row = await session.get(Conversation, conversation_id)
        if row is None:
            row = Conversation(id=conversation_id, title=title[:400], project_id=project_id or "")
            session.add(row)
        row.messages_json = blob
        if title:
            row.title = title[:400]
        if project_id:
            row.project_id = project_id
        await session.commit()


async def open_conversation(conversation_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        row = await session.get(Conversation, conversation_id)
        if row is None:
            return {}
        messages = _messages_from_json(row.messages_json)
        return {
            "id": row.id,
            "title": row.title or "Chat",
            "task_id": row.task_id or "",
            "project_id": row.project_id or "",
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }


async def list_owner_conversations(limit: int = 40) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Conversation)
                .where(Conversation.task_id == "")
                .order_by(Conversation.updated_at.desc())
                .limit(max(1, min(limit, 200)))
            )
        ).scalars().all()
        return [
            {
                "conversation_id": row.id,
                "title": row.title or "Chat",
                "project_id": row.project_id or "",
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            }
            for row in rows
        ]
