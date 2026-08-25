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

from app.agent.loop import AgentRuntime
from app.agent.recovery import RecoveryTracker, alternate_tools, classify_error
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
        self.offered: list[list[str]] = []

    async def chat(self, messages, tools=None, **kwargs) -> ChatResult:
        self.calls += 1
        self.offered.append([t.get("function", {}).get("name") for t in (tools or []) if t.get("function")])
        if self.calls > len(self.results):
            raise AssertionError(f"Loop kept calling the model (call {self.calls})")
        return self.results[self.calls - 1]


class RecoveryPolicyTests(unittest.TestCase):
    def test_missing_path_classified(self) -> None:
        self.assertEqual(
            classify_error("terminal", {"command": "Get-Item C:\\nope"}, "ERROR: Path not found"),
            "missing",
        )

    def test_two_terminal_failures_switch_to_filesystem(self) -> None:
        tracker = RecoveryTracker()
        args = {"command": "Get-Item C:\\this-path-does-not-exist-jarvis-xyz"}
        self.assertIsNone(tracker.record("terminal", args, False, "ERROR: Path not found"))
        plan = tracker.record("terminal", args, False, "ERROR: Path not found")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.failed_tool, "terminal")
        self.assertIn("filesystem", plan.prefer_tools)
        self.assertIn("python", plan.prefer_tools)
        self.assertIn("terminal", plan.avoid_tools)
        self.assertIn("Do not call `terminal`", plan.prompt)
        self.assertIn("missing", plan.prompt)
        schemas = [
            {"type": "function", "function": {"name": name}}
            for name in ("terminal", "filesystem", "python", "browser")
        ]
        names = [s["function"]["name"] for s in tracker.tools_for_next_round(schemas)]
        self.assertNotIn("terminal", names)
        self.assertIn("filesystem", names)

    def test_success_clears_fail_streak_and_restores_tools(self) -> None:
        tracker = RecoveryTracker()
        tracker.record("filesystem", {"action": "write", "path": "a"}, False, "ERROR: denied")
        tracker.record("filesystem", {"action": "write", "path": "a"}, False, "ERROR: denied")
        self.assertIn("filesystem", tracker.avoid_tools)
        tracker.record("python", {"action": "run_code"}, True, "ok")
        self.assertEqual(tracker.fail_streak, 0)
        self.assertEqual(tracker.avoid_tools, set())

    def test_alternates_are_not_the_failed_tool(self) -> None:
        for tool in ("filesystem", "terminal", "python", "browser"):
            alts = alternate_tools(tool)
            self.assertTrue(alts)
            self.assertNotIn(tool, alts)

    def test_recovery_plan_is_not_a_same_tool_poll_cutoff(self) -> None:
        tracker = RecoveryTracker()
        tracker.record("filesystem", {"action": "list", "path": "x"}, False, "ERROR: nope")
        plan = tracker.record("filesystem", {"action": "list", "path": "x"}, False, "ERROR: nope")
        assert plan is not None
        self.assertIn("Preferred tools", plan.prompt)
        self.assertNotIn("poll", plan.prompt.lower())


class AgentLoopRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t03-"))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.settings = AppSettings(allowed_directories=[str(self.tmp)], autonomy="autonomous")
        REGISTRY.apply_settings(self.settings)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _noop(self, *args, **kwargs):
        return None

    async def test_repeated_filesystem_failure_excludes_tool_and_recovers_via_python(self) -> None:
        target = self.tmp / "recovery.txt"
        forbidden = r"C:\Windows\jarvis-t03-forbidden.txt"
        prompt = f"Write RECOVERED to {target}. A first path may fail; recover with another tool."
        code = (
            f"p = r'{target}'\n"
            "open(p, 'w', encoding='utf-8').write('RECOVERED')\n"
            "print(p)"
        )
        results = [
            ChatResult(tool_calls=[_tool_call("c1", "filesystem", {"action": "write", "path": forbidden, "content": "RECOVERED"})]),
            ChatResult(tool_calls=[_tool_call("c2", "filesystem", {"action": "write", "path": forbidden, "content": "RECOVERED"})]),
            ChatResult(tool_calls=[_tool_call("c3", "python", {"action": "run_code", "code": code})]),
            ChatResult(content="recovered with python"),
        ]
        provider = ScriptedProvider(results)
        manager = loop_manager(provider, record_timings=noop, load=noop)
        runtime = AgentRuntime()
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager),
            patch("app.agent.loop.load_settings", lambda: self.settings),
        ):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertGreaterEqual(len(provider.offered), 3)
        self.assertIn("filesystem", provider.offered[0])
        self.assertNotIn("filesystem", provider.offered[2])
        self.assertIn("python", provider.offered[2])
        self.assertEqual(stored.status, "completed")
        self.assertTrue(target.exists())
        self.assertIn("RECOVERED", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
