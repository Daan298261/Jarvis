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

from manager_mock import loop_manager, noop

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.completion import CompletionTracker
from app.agent.loop import AgentRuntime
from app.agent.skills import (
    derive_skill_name,
    format_skill_hint,
    get_skill,
    list_skills,
    match_skills,
    promote_from_trajectory,
)
from app.agent.trajectories import record_trajectory
from app.config import AppSettings
from app.db.models import Base
from app.providers.base import ChatResult
from app.tools.registry import REGISTRY
from app.tools.skill import SkillTool


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
        self.last_tools = []

    async def chat(self, messages, tools=None, **kwargs) -> ChatResult:
        self.calls += 1
        self.last_messages = messages
        self.last_tools = tools or []
        if self.calls > len(self.results):
            raise AssertionError(f"Loop kept calling the model (call {self.calls})")
        return self.results[self.calls - 1]


class ReusableSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t13-"))
        self.traj_patch = patch(
            "app.agent.trajectories.trajectory_store_path",
            lambda: self.tmp / "trajectories.json",
        )
        self.skill_patch = patch(
            "app.agent.skills.skill_store_path",
            lambda: self.tmp / "skills.json",
        )
        self.traj_patch.start()
        self.skill_patch.start()

    def tearDown(self) -> None:
        self.skill_patch.stop()
        self.traj_patch.stop()

    def _primes_tracker(self) -> CompletionTracker:
        tracker = CompletionTracker()
        tracker.record("python", {"code": "print(2)", "path": str(self.tmp / "primes.py")}, True, "ok")
        tracker.record(
            "filesystem",
            {"action": "write", "path": str(self.tmp / "primes.txt"), "content": "SECRET"},
            True,
            "Wrote primes.txt",
        )
        tracker.record("filesystem", {"action": "read", "path": str(self.tmp / "primes.txt")}, True, "2")
        return tracker

    def test_one_success_does_not_create_a_skill(self) -> None:
        prompt = "Create a small Python program that writes 100 primes to primes.txt"
        record_trajectory(prompt, self._primes_tracker())
        self.assertIsNone(get_skill("run_python_primes"))
        self.assertFalse(any(row["name"] == "run_python_primes" for row in list_skills() if not row["builtin"]))

    def test_two_successes_promote_named_skill(self) -> None:
        prompt = "Create a small Python program that writes 100 primes to primes.txt"
        record_trajectory(prompt, self._primes_tracker())
        second = record_trajectory(prompt, self._primes_tracker())
        assert second is not None
        self.assertTrue(second.stable)
        skill = promote_from_trajectory(second)
        assert skill is not None
        self.assertEqual(skill.name, "run_python_primes")
        self.assertIn("python", skill.required_tools)
        self.assertTrue(skill.parameters)
        self.assertTrue(skill.verification)
        self.assertTrue(skill.recovery)
        stored = json.loads((self.tmp / "skills.json").read_text(encoding="utf-8"))
        self.assertTrue(any(row["name"] == "run_python_primes" for row in stored))
        self.assertNotIn("SECRET", json.dumps(stored))
        hint = format_skill_hint("Write the first 100 primes into primes.txt using a Python program")
        self.assertIn("`run_python_primes`", hint)
        self.assertIn("do not rediscover", hint.lower())
        self.assertEqual(format_skill_hint("Look up the latest news on wikipedia"), "")

    def test_builtin_example_com_skill_matches(self) -> None:
        matches = match_skills(
            "Open a browser, visit https://example.com, read the page title, and save that title to page-title.txt",
            "browser",
        )
        self.assertTrue(matches)
        self.assertEqual(matches[0].name, "save_example_com_title")
        hint = format_skill_hint(
            "Open a browser, visit https://example.com, read the page title, and save that title to page-title.txt",
            "browser",
        )
        self.assertIn("save_example_com_title", hint)
        self.assertIn("Verification:", hint)
        self.assertIn("Recovery:", hint)

    def test_example_com_skill_does_not_match_unrelated_title_task(self) -> None:
        matches = match_skills(
            "Open a browser, visit https://unfamiliar-intranet.test/admin, read the page title, and save it.",
            "browser",
        )
        names = [row.name for row in matches]
        self.assertNotIn("save_example_com_title", names)

    def test_derive_name_is_stable(self) -> None:
        name = derive_skill_name(
            "software_engineering",
            [{"tool": "python", "action": ""}, {"tool": "filesystem", "action": "write", "target": "primes.txt"}],
            "write primes",
        )
        self.assertEqual(name, "run_python_primes")


class SkillToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t13-tool-"))
        self.traj_patch = patch(
            "app.agent.trajectories.trajectory_store_path",
            lambda: self.tmp / "trajectories.json",
        )
        self.skill_patch = patch(
            "app.agent.skills.skill_store_path",
            lambda: self.tmp / "skills.json",
        )
        self.traj_patch.start()
        self.skill_patch.start()

    async def asyncTearDown(self) -> None:
        self.skill_patch.stop()
        self.traj_patch.stop()

    async def test_list_includes_builtin_and_get_returns_steps(self) -> None:
        tool = SkillTool()
        listed = await tool.execute(action="list")
        self.assertTrue(listed.success)
        self.assertIn("save_example_com_title", listed.output)
        got = await tool.execute(action="get", name="save_example_com_title")
        self.assertTrue(got.success)
        self.assertIn("browser save_title", got.output)
        self.assertIn("Verification:", got.output)
        missing = await tool.execute(action="get", name="no_such_skill")
        self.assertFalse(missing.success)


class SkillLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t13-loop-"))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.settings = AppSettings(allowed_directories=[str(self.tmp)], autonomy="autonomous")
        REGISTRY.apply_settings(self.settings)
        self.traj_patch = patch(
            "app.agent.trajectories.trajectory_store_path",
            lambda: self.tmp / "trajectories.json",
        )
        self.skill_patch = patch(
            "app.agent.skills.skill_store_path",
            lambda: self.tmp / "skills.json",
        )
        self.traj_patch.start()
        self.skill_patch.start()

    async def asyncTearDown(self) -> None:
        self.skill_patch.stop()
        self.traj_patch.stop()
        await self.engine.dispose()

    async def _noop(self, *args, **kwargs):
        return None

    async def test_loop_injects_named_skill_on_similar_task(self) -> None:
        target = self.tmp / "primes.txt"
        prompt = f"Create a small Python program that writes 100 primes to {target}."
        runtime = AgentRuntime()

        async def _run_once(content: str, manager) -> None:
            with (
                patch("app.agent.loop.SessionLocal", self.sessions),
                patch("app.events.SessionLocal", self.sessions),
                patch("app.agent.resume.SessionLocal", self.sessions),
                patch("app.agent.loop.MANAGER", manager),
                patch("app.agent.loop.load_settings", lambda: self.settings),
            ):
                task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
                await runtime._tasks[task.id]

        write = _tool_call("c1", "filesystem", {"action": "write", "path": str(target), "content": "2\n3"})
        first = ScriptedProvider([ChatResult(tool_calls=[write])])
        await _run_once(
            prompt,
            loop_manager(
                provider=first,
                profile="fast",
                thinking_at_process=False,
                record_timings=self._noop,
                load=self._noop,
            ),
        )
        await _run_once(
            prompt,
            loop_manager(
                provider=ScriptedProvider([ChatResult(tool_calls=[write])]),
                profile="fast",
                thinking_at_process=False,
                record_timings=self._noop,
                load=self._noop,
            ),
        )
        provider = ScriptedProvider([ChatResult(tool_calls=[write])])
        await _run_once(
            prompt,
            loop_manager(
                provider=provider,
                profile="fast",
                thinking_at_process=False,
                record_timings=self._noop,
                load=self._noop,
            ),
        )
        blobs = [
            message.content if isinstance(message.content, str) else str(message.content)
            for message in provider.last_messages
            if message.role == "user"
        ]
        combined = "\n".join(blobs)
        self.assertIn("Named skill", combined)
        self.assertIn("do not rediscover", combined.lower())
        names = {(schema.get("function") or {}).get("name") for schema in provider.last_tools}
        self.assertIn("skill", names)
