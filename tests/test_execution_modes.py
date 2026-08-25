from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.completion import CompletionTracker
from app.agent.execution import CRITIC_PROMPT, FAST_PLAN, RELIABLE_PLAN, ready_to_complete, resolve_mode
from app.agent.loop import AgentRuntime
from app.agent.recovery import RecoveryTracker
from app.config import AppSettings
from app.db.models import Base, Task
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
        self.thinking: list = []
        self.last_messages = []

    async def chat(self, messages, tools=None, **kwargs) -> ChatResult:
        self.calls += 1
        self.thinking.append(kwargs.get("thinking"))
        self.last_messages = messages
        if self.calls > len(self.results):
            raise AssertionError(f"Loop kept calling the model (call {self.calls})")
        return self.results[self.calls - 1]


class ExecutionModePolicyTests(unittest.TestCase):
    def test_modes_are_distinct_from_each_other(self) -> None:
        fast = resolve_mode("fast")
        balanced = resolve_mode("balanced")
        reliable = resolve_mode("reliable")
        self.assertEqual(fast.name, "fast")
        self.assertEqual(balanced.name, "balanced")
        self.assertEqual(reliable.name, "reliable")
        self.assertLess(fast.max_steps, balanced.max_steps)
        self.assertLess(balanced.max_steps, reliable.max_steps)
        self.assertLess(fast.tool_round_budget, reliable.tool_round_budget)
        self.assertFalse(fast.allow_thinking)
        self.assertTrue(balanced.allow_thinking)
        self.assertTrue(reliable.allow_thinking)
        self.assertEqual(fast.max_repairs, 0)
        self.assertEqual(balanced.max_repairs, 1)
        self.assertEqual(reliable.max_repairs, 2)
        self.assertTrue(reliable.require_verified_read)
        self.assertFalse(fast.require_verified_read)
        self.assertIn("one-line", fast.plan_prompt)
        self.assertIn("THREE candidate", reliable.plan_prompt)
        self.assertEqual(resolve_mode("quality").name, "reliable")
        self.assertEqual(resolve_mode("nope").name, "balanced")

    def test_fast_recovery_switches_on_first_failure(self) -> None:
        tracker = RecoveryTracker(fail_after_tool=1, fail_after_streak=2)
        plan = tracker.record("terminal", {"command": "x"}, False, "Path not found")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("filesystem", plan.prefer_tools)

    def test_balanced_recovery_waits_for_second_failure(self) -> None:
        tracker = RecoveryTracker()
        self.assertIsNone(tracker.record("terminal", {"command": "x"}, False, "Path not found"))
        self.assertIsNotNone(tracker.record("terminal", {"command": "x"}, False, "Path not found"))

    def test_reliable_ready_requires_read_after_write(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-t07-ready-"))
        path = tmp / "out.txt"
        path.write_text("hello", encoding="utf-8")
        tracker = CompletionTracker()
        prompt = f"Write hello to {path}"
        tracker.record("filesystem", {"action": "write", "path": str(path), "content": "hello"}, True, f"Wrote {path}")
        self.assertFalse(ready_to_complete(tracker, prompt, resolve_mode("reliable")))
        self.assertTrue(ready_to_complete(tracker, prompt, resolve_mode("fast")))
        tracker.record("filesystem", {"action": "read", "path": str(path)}, True, "hello")
        self.assertTrue(ready_to_complete(tracker, prompt, resolve_mode("reliable")))


class ExecutionModeLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t07-"))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.settings = AppSettings(
            allowed_directories=[str(self.tmp)],
            autonomy="autonomous",
            execution_mode="balanced",
        )
        REGISTRY.apply_settings(self.settings)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _noop(self, *args, **kwargs):
        return None

    def _manager(self, provider) -> SimpleNamespace:
        return loop_manager(
            provider,
            loaded=True,
            profile="balanced",
            thinking_at_process=True,
            record_timings=self._noop,
            load=self._noop,
        )

    async def _run(
        self,
        prompt: str,
        results: list[ChatResult],
        *,
        profile: str = "balanced",
        execution_mode: str = "balanced",
    ) -> tuple[Task, ScriptedProvider]:
        provider = ScriptedProvider(results)
        runtime = AgentRuntime()
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.resume.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", self._manager(provider)),
            patch("app.agent.loop.load_settings", lambda: self.settings),
        ):
            task = await runtime.create_task(
                prompt,
                autonomy="autonomous",
                profile=profile,
                execution_mode=execution_mode,
            )
            await runtime._tasks[task.id]
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
            assert stored is not None
            return stored, provider

    async def test_create_stores_mode_independently_of_profile(self) -> None:
        target = self.tmp / "fast.txt"
        stored, provider = await self._run(
            f"Write HI to {target} and verify the file.",
            [
                ChatResult(
                    tool_calls=[
                        _tool_call("c1", "filesystem", {"action": "write", "path": str(target), "content": "HI"})
                    ]
                )
            ],
            profile="balanced",
            execution_mode="fast",
        )
        self.assertEqual(stored.execution_mode, "fast")
        self.assertEqual(stored.profile, "balanced")
        self.assertEqual(stored.status, "completed")
        first_user = next(m.content for m in provider.last_messages if m.role == "user")
        self.assertIn("one-line", first_user if isinstance(first_user, str) else str(first_user))
        self.assertFalse(any(provider.thinking))

    async def test_fast_disables_thinking_on_balanced_profile(self) -> None:
        target = self.tmp / "think.txt"
        _stored, provider = await self._run(
            f"Write OK to {target}.",
            [
                ChatResult(
                    tool_calls=[
                        _tool_call("c1", "filesystem", {"action": "write", "path": str(target), "content": "OK"})
                    ]
                )
            ],
            profile="balanced",
            execution_mode="fast",
        )
        self.assertEqual(provider.thinking, [False])

    async def test_reliable_uses_best_of_n_plan_and_critic(self) -> None:
        nested = self.tmp / "nested"
        nested.mkdir()
        stored, provider = await self._run(
            f"Inspect {self.tmp} then inspect {nested}. Do not create files.",
            [
                ChatResult(
                    tool_calls=[_tool_call("c1", "filesystem", {"action": "list", "path": str(self.tmp)})]
                ),
                ChatResult(
                    tool_calls=[_tool_call("c2", "filesystem", {"action": "list", "path": str(nested)})]
                ),
                ChatResult(content="Inspection complete."),
            ],
            profile="balanced",
            execution_mode="reliable",
        )
        self.assertEqual(stored.execution_mode, "reliable")
        self.assertGreaterEqual(provider.calls, 3)
        blobs = []
        for message in provider.last_messages:
            if message.role == "user":
                blobs.append(message.content if isinstance(message.content, str) else str(message.content))
        self.assertTrue(any("THREE candidate" in blob for blob in blobs) or RELIABLE_PLAN in "\n".join(blobs))
        self.assertTrue(any(CRITIC_PROMPT[:20] in blob for blob in blobs))
        self.assertTrue(FAST_PLAN not in "\n".join(blobs))


if __name__ == "__main__":
    unittest.main()
