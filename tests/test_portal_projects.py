from __future__ import annotations

import pytest

from app.db.session import SessionLocal, configure_database, init_db
from app.projects import portal_store


@pytest.fixture
async def portal_db(tmp_path):
    configure_database(path=tmp_path / "portal.db")
    await init_db()
    yield
    configure_database(path=tmp_path / "portal.db")


@pytest.mark.asyncio
async def test_create_project_and_link_task(portal_db):
    project = await portal_store.create_project("Alpha")
    await portal_store.link_member(project["id"], "task", "task-1")
    listed = await portal_store.list_projects()
    assert len(listed) == 1
    assert listed[0]["taskIds"] == ["task-1"]


@pytest.mark.asyncio
async def test_owner_chat_link_sets_conversation_project_id(portal_db):
    from app.db.models import Conversation

    project = await portal_store.create_project("Chats")
    conv_id = "conv-project-link"
    async with SessionLocal() as session:
        session.add(Conversation(id=conv_id, title="T", messages_json="[]", task_id=""))
        await session.commit()

    await portal_store.link_member(project["id"], "owner_chat", conv_id)
    async with SessionLocal() as session:
        row = await session.get(Conversation, conv_id)
        assert row is not None
        assert row.project_id == project["id"]

    listed = await portal_store.list_projects()
    assert conv_id in listed[0]["conversationIds"]

    await portal_store.unlink_member("owner_chat", conv_id)
    async with SessionLocal() as session:
        row = await session.get(Conversation, conv_id)
        assert row is not None
        assert row.project_id == ""


@pytest.mark.asyncio
async def test_import_local_idempotent_links(portal_db):
    legacy_id = "legacy-project-1"
    task_id = "task-legacy-1"
    payload = [{"id": legacy_id, "name": "Legacy", "taskIds": [task_id]}]
    assert await portal_store.import_local_projects(payload) == 1
    assert await portal_store.import_local_projects(payload) == 0
    listed = await portal_store.list_projects()
    assert len(listed) == 1
    assert listed[0]["taskIds"] == [task_id]


@pytest.mark.asyncio
async def test_owner_conversation_roundtrip(portal_db):
    from app.providers.base import ChatMessage

    cid = "conv-test-1"
    await portal_store.save_owner_conversation(
        cid,
        [ChatMessage(role="user", content="Hi"), ChatMessage(role="assistant", content="Hello.")],
        title="Hi",
    )
    loaded = await portal_store.load_owner_conversation(cid)
    assert len(loaded) == 2
    rows = await portal_store.list_owner_conversations()
    assert any(row["conversation_id"] == cid for row in rows)
