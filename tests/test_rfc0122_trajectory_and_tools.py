import json

import pytest
from sqlalchemy import select

from app.agent.compaction import LESSONS_MARKER, compact_history
from app.agent.tool_exposure import schemas_for
from app.agent.trajectory import LESSONS_HEADER, gated_trajectory_lessons, relevant_trajectories
from app.db.models import Trajectory
from app.db.session import SessionLocal
from app.providers.base import ChatMessage


async def _insert_traj(goal: str, task_class: str = "conversation", tools=None, recovery: str = "") -> None:
    async with SessionLocal() as session:
        session.add(
            Trajectory(
                task_id="t-rfc0122",
                task_class=task_class,
                goal=goal,
                outcome="completed",
                tools_json=json.dumps(tools or []),
                recovery=recovery,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_denylist_last_message_never_injected(jarvis_env):
    await _insert_traj("what was my last message to you?")
    await _insert_traj("what was my last message to you?")
    picked = await relevant_trajectories("conversation", "companion router ports for portforwarding")
    assert picked == []
    block, injected, dropped = await gated_trajectory_lessons(
        "conversation",
        "companion router ports for portforwarding",
    )
    assert not injected
    assert not block
    assert any("last_message" in reason for reason in dropped)


@pytest.mark.asyncio
async def test_ports_qa_empty_tool_schemas(jarvis_env):
    prompt = "what ports do i need for the companion app, for portforwarding in the router"
    schemas = schemas_for("conversation", prompt=prompt, needs_tools=False)
    names = {item["function"]["name"] for item in schemas}
    assert "filesystem" not in names
    assert names <= {"request_capability"}


@pytest.mark.asyncio
async def test_compact_drops_lessons_from_system_head():
    junk = f"{LESSONS_HEADER}\n- bad -> completed using none"
    messages = [
        ChatMessage(role="system", content=f"Identity\n\n{junk}\n\nTool exposure: filesystem"),
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="assistant", content="hi"),
        ChatMessage(role="user", content="ports?"),
    ]
    compacted = compact_history(messages, keep_last=2, drop_head_injections=True)
    system = compacted[0].content or ""
    assert LESSONS_MARKER in junk
    assert LESSONS_MARKER not in system
    assert "Tool exposure" not in system
