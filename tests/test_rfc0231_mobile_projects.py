from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.api.companion import router
from app.mobile import identity, service
from app.db.models import Conversation, Task
from app.db.session import SessionLocal
from app.projects import portal_store


@pytest.mark.asyncio
async def test_shared_projects_and_owner_chat_roundtrip(jarvis_env):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[identity.require_device] = lambda: {"id": "test-phone"}
    cid = str(uuid.uuid4())
    async with SessionLocal() as db:
        db.add(Conversation(id=cid, title="Existing desktop chat", messages_json=json.dumps([
            {"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Welcome"}]), task_id=""))
        await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/companion/projects", json={"name": "Android"})).json()
        pid = project["id"]
        assert (await client.put(f"/api/companion/projects/{pid}/conversations/{cid}")).status_code == 200
        assert (await portal_store.list_projects())[0]["conversationIds"] == [cid]
        assert (await client.patch(f"/api/companion/projects/{pid}", json={"name": "Shared"})).status_code == 200
        assert (await portal_store.list_projects())[0]["name"] == "Shared"
        chats = (await client.get(f"/api/companion/projects/{pid}/conversations")).json()
        assert chats[0]["id"] == cid and chats[0]["project_id"] == pid
        detail = await service.conversation_detail(cid)
        assert [m["text"] for m in detail["messages"]] == ["Hello", "Welcome"]
        assert (await client.post("/api/companion/projects", json={"name": "   "})).status_code == 422
        assert (await client.put(f"/api/companion/projects/{uuid.uuid4()}/conversations/{cid}")).status_code == 404


@pytest.mark.asyncio
async def test_phone_task_chat_is_readable_in_desktop_project(jarvis_env):
    cid = str(uuid.uuid4())
    async with SessionLocal() as db:
        db.add(Task(id="phone-task", title="Phone", prompt="Hello", status="completed", result="Desktop answer"))
        db.add(Conversation(id=cid, title="Phone chat", task_id="phone-task", messages_json=json.dumps([
            {"role": "user", "text": "Hello", "task_id": "phone-task"}])))
        await db.commit()
    project = await portal_store.create_project("Shared phone chat")
    await portal_store.link_member(project["id"], "owner_chat", cid)
    detail = await portal_store.open_conversation(cid)
    assert [m["content"] for m in detail["messages"]] == ["Hello", "Desktop answer"]
    assert [m.content for m in await portal_store.load_owner_conversation(cid)] == ["Hello", "Desktop answer"]


@pytest.mark.asyncio
async def test_project_routes_require_paired_device(jarvis_env):
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/companion/projects")).status_code in (401, 403)
        assert (await client.post("/api/companion/projects", json={"name": "Denied"})).status_code in (401, 403)
