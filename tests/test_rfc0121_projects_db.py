from __future__ import annotations

import pytest

from app.db.models import Conversation
from app.db.session import SessionLocal, configure_database, init_db
from app.projects import portal_store


@pytest.fixture
async def portal_db(tmp_path):
    configure_database(path=tmp_path / "portal.db")
    await init_db()
    yield
    configure_database(path=tmp_path / "portal.db")


@pytest.mark.asyncio
async def test_rfc0121_conversation_project_id_via_link(portal_db):
    """RFC-0121: chats live in internal DB with project_id, not portal-only grouping."""
    project = await portal_store.create_project("RFC-0121")
    conv_id = "rfc-0121-conv"
    async with SessionLocal() as session:
        session.add(Conversation(id=conv_id, title="Chat", messages_json="[]", task_id=""))
        await session.commit()

    await portal_store.link_member(project["id"], "owner_chat", conv_id)
    async with SessionLocal() as session:
        row = await session.get(Conversation, conv_id)
        assert row is not None
        assert row.project_id == project["id"]
