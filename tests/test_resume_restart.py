from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.loop import AgentRuntime
from app.agent.prompts import FOLLOW_UP_NUDGE
from app.agent.resume import recover_orphaned_tasks
from app.config import AppSettings
from app.db.models import Base, Task, ToolCallRecord, utcnow
from app.providers.base import ChatResult
from app.tools.registry import REGISTRY

from manager_mock import loop_manager, noop


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class ScriptedProvider:
    def __init__(self, results: list[ChatResult]) -> None:
        self.results = results
        self.calls = 0
        self.last_messages = []

    async def chat(self, messages, tools=None, **kwargs) -> ChatResult:
        self.calls += 1
        self.last_messages = messages
        if self.calls > len(self.results):
            raise AssertionError(f"Loop kept calling the model (call {self.calls})")
        return self.results[self.calls - 1]


class ResumeAcrossRestartTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t06-"))
        self.db = self.tmp / "jarvis.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db.as_posix()}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.settings = AppSettings(allowed_directories=[str(self.tmp)], autonomy="autonomous")
        REGISTRY.apply_settings(self.settings)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def _patches(self, manager):
        stack = ExitStack()
        stack.enter_context(patch("app.agent.loop.SessionLocal", self.sessions))
        stack.enter_context(patch("app.events.SessionLocal", self.sessions))
        stack.enter_context(patch("app.agent.resume.SessionLocal", self.sessions))
        stack.enter_context(patch("app.agent.loop.MANAGER", manager))
        stack.enter_context(patch("app.agent.loop.load_settings", lambda: self.settings))
        return stack

    async def _noop(self, *args, **kwargs):
        return None

    def _manager(self, provider) -> SimpleNamespace:
        return loop_manager(
            provider,
            profile="fast",
            thinking_at_process=False,
            record_timings=self._noop,
            load=self._noop,
        )

    async def test_orphaned_running_task_is_interrupted(self) -> None:
        async with self.sessions() as session:
            session.add(
                Task(
                    id="t-run",
                    title="running",
                    prompt="do work",
                    status="running",
                    stage="act",
                    current_action="Waiting on model",
                )
            )
            session.add(
                Task(
                    id="t-wait",
                    title="waiting",
                    prompt="confirm",
                    status="waiting",
                    waiting_for_confirmation=True,
                    confirmation_payload="{}",
                )
            )
            await session.commit()
        with patch("app.agent.resume.SessionLocal", self.sessions):
            changed = await recover_orphaned_tasks()
        self.assertEqual(changed, 1)
        async with self.sessions() as session:
            running = await session.get(Task, "t-run")
            waiting = await session.get(Task, "t-wait")
        assert running and waiting
        self.assertEqual(running.status, "interrupted")
        self.assertIn("Continue", running.current_action)
        self.assertEqual(waiting.status, "waiting")

    async def test_history_and_continue_survive_new_runtime(self) -> None:
        target = self.tmp / "resume.txt"
        prompt = f"Write FIRST to {target} and verify the file."
        first = [
            ChatResult(
                tool_calls=[_tool_call("c1", "filesystem", {"action": "write", "path": str(target), "content": "FIRST"})]
            ),
        ]
        provider = ScriptedProvider(first)
        runtime = AgentRuntime()
        with self._patches(self._manager(provider)):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        self.assertEqual(target.read_text(encoding="utf-8"), "FIRST")
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
            events = stored is not None
            calls = (await session.execute(select(ToolCallRecord).where(ToolCallRecord.task_id == task.id))).scalars().all()
        assert stored is not None
        self.assertEqual(stored.status, "completed")
        self.assertTrue(stored.conversation_json)
        self.assertGreaterEqual(len(calls), 1)
        self.assertTrue(events)

        follow = f"Append the word RESUMED to {target}."
        second = [
            ChatResult(
                tool_calls=[
                    _tool_call(
                        "c2",
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "FIRST\nRESUMED"},
                    )
                ]
            ),
        ]
        provider2 = ScriptedProvider(second)
        resumed = AgentRuntime()
        with self._patches(self._manager(provider2)):
            again = await resumed.continue_task(task.id, follow)
            await resumed._tasks[again.id]
        self.assertIn("RESUMED", target.read_text(encoding="utf-8"))
        user_blobs = []
        for message in provider2.last_messages:
            if message.role == "user":
                user_blobs.append(message.content if isinstance(message.content, str) else str(message.content))
        self.assertTrue(any("Continue the existing task" in blob for blob in user_blobs))
        async with self.sessions() as session:
            after = await session.get(Task, task.id)
        assert after is not None
        self.assertEqual(after.status, "completed")
        self.assertIn("Follow-up", after.prompt)

    async def test_continue_follow_up_ignores_text_only_completion(self) -> None:
        target = self.tmp / "follow.txt"
        prompt = f"Write FIRST to {target} and verify the file."
        provider = ScriptedProvider(
            [
                ChatResult(
                    tool_calls=[_tool_call("c1", "filesystem", {"action": "write", "path": str(target), "content": "FIRST"})]
                ),
            ]
        )
        runtime = AgentRuntime()
        with self._patches(self._manager(provider)):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        self.assertEqual(target.read_text(encoding="utf-8"), "FIRST")

        follow = f"Append the word RESUMED to {target}."
        provider2 = ScriptedProvider(
            [
                ChatResult(content="The file already exists. Done."),
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c2",
                            "filesystem",
                            {"action": "write", "path": str(target), "content": "FIRST\nRESUMED"},
                        )
                    ]
                ),
            ]
        )
        resumed = AgentRuntime()
        with self._patches(self._manager(provider2)):
            again = await resumed.continue_task(task.id, follow)
            await resumed._tasks[again.id]
        self.assertGreaterEqual(provider2.calls, 2)
        self.assertIn("RESUMED", target.read_text(encoding="utf-8"))
        self.assertTrue(any(FOLLOW_UP_NUDGE[:40] in (m.content or "") for m in provider2.last_messages if m.role == "user"))

    async def test_continue_rebuilds_from_tool_records_without_conversation(self) -> None:
        target = self.tmp / "orphan.txt"
        target.write_text("SEED", encoding="utf-8")
        async with self.sessions() as session:
            session.add(
                Task(
                    id="t-orphan",
                    title="orphan",
                    prompt=f"Write READY to {target}",
                    status="interrupted",
                    conversation_json="[]",
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            session.add(
                ToolCallRecord(
                    task_id="t-orphan",
                    tool_name="filesystem",
                    arguments_json=json.dumps({"action": "write", "path": str(target), "content": "SEED"}),
                    output=f"Wrote {target}",
                    success=True,
                )
            )
            await session.commit()
        follow = f"Append RESUMED to {target}."
        provider = ScriptedProvider(
            [
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c1",
                            "filesystem",
                            {"action": "write", "path": str(target), "content": "SEED\nRESUMED"},
                        )
                    ]
                )
            ]
        )
        runtime = AgentRuntime()
        with self._patches(self._manager(provider)):
            task = await runtime.continue_task("t-orphan", follow)
            await runtime._tasks[task.id]
        self.assertIn("RESUMED", target.read_text(encoding="utf-8"))
        self.assertTrue(any(m.role == "tool" for m in provider.last_messages))


if __name__ == "__main__":
    unittest.main()
