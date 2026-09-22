from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Conversation, PortalProject, PortalProjectLink
from app.db.session import SessionLocal
from app.main import app
from app.projects.paths import project_media_dir
from app.tools.registry import REGISTRY


@pytest.fixture
def client(jarvis_env):
    return TestClient(app)


def test_project_media_dir_stub(jarvis_env):
    pid = str(uuid.uuid4())
    media = project_media_dir(pid)
    assert media.is_dir()
    assert media.name == "media"


@pytest.mark.asyncio
async def test_projects_api_and_links(jarvis_env, client, monkeypatch):
    monkeypatch.setattr("app.auth.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.main.load_settings", lambda: jarvis_env["settings"])
    created = client.post("/api/projects", json={"name": "RFC-0129"})
    assert created.status_code == 200
    project_id = created.json()["id"]

    task_id = str(uuid.uuid4())
    assert client.post(
        f"/api/projects/{project_id}/links",
        json={"link_type": "task", "link_id": task_id},
    ).status_code == 200

    conv_id = str(uuid.uuid4())
    async with SessionLocal() as db:
        db.add(Conversation(id=conv_id, title="Hello", messages_json="[]", task_id=""))
        await db.commit()

    assert client.post(
        f"/api/projects/{project_id}/links",
        json={"link_type": "owner_chat", "link_id": conv_id},
    ).status_code == 200

    row = next(p for p in client.get("/api/projects").json()["projects"] if p["id"] == project_id)
    assert task_id in row["taskIds"]
    assert conv_id in row["conversationIds"]

    repo_path = r"C:\Users\daanv\Documents\Projects\Jarvis\Jarvis"
    assert client.post(
        f"/api/projects/{project_id}/links",
        json={"link_type": "repo", "link_id": repo_path},
    ).status_code == 200
    row = next(p for p in client.get("/api/projects").json()["projects"] if p["id"] == project_id)
    assert repo_path in row["repoPaths"]
    assert client.delete("/api/projects/unlink", params={"link_type": "repo", "link_id": repo_path}).status_code == 200

    opened = client.get(f"/api/projects/conversations/{conv_id}")
    assert opened.status_code == 200
    assert opened.json()["title"] == "Hello"

    client.delete(f"/api/projects/{project_id}")


@pytest.mark.asyncio
async def test_chat_projects_tool(jarvis_env, client, monkeypatch):
    monkeypatch.setattr("app.auth.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.main.load_settings", lambda: jarvis_env["settings"])
    legacy_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    imported = client.post(
        "/api/projects/import-local",
        json={"projects": [{"id": legacy_id, "name": "Imported", "taskIds": [task_id]}]},
    )
    assert imported.status_code == 200

    tool = REGISTRY.tools["chat_projects"]
    listed = await tool.execute(action="list_projects")
    assert listed.success
    moved = await tool.execute(action="move_task", task_id=task_id, project_id=legacy_id)
    assert moved.success

    async with SessionLocal() as db:
        assert await db.get(PortalProject, legacy_id) is not None
        links = (await db.execute(select(PortalProjectLink).where(PortalProjectLink.link_id == task_id))).scalars().all()
        assert links
