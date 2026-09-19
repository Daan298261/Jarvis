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
