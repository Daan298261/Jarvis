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
from app.agent.trajectories import (
    MAX_TRAJECTORIES,
    format_trajectory_hint,
    record_trajectory,
    steps_from_tracker,
)
from app.config import AppSettings
from app.db.models import Base, Task
from app.providers.base import ChatResult
from app.tools.registry import REGISTRY


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


class TrajectoryMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t12-"))
        self.patcher = patch(
            "app.agent.trajectories.trajectory_store_path",
            lambda: self.tmp / "trajectories.json",
        )
        self.skill_patcher = patch(
            "app.agent.skills.skill_store_path",
            lambda: self.tmp / "skills.json",
        )
        self.patcher.start()
        self.skill_patcher.start()

    def tearDown(self) -> None:
        self.skill_patcher.stop()
        self.patcher.stop()

    def test_successful_sequence_is_reused_on_similar_prompt(self) -> None:
        tracker = CompletionTracker()
        tracker.record(
            "python",
            {"code": "print(2)", "path": str(self.tmp / "primes.py")},
            True,
            "ok",
        )
        tracker.record(
            "filesystem",
            {"action": "write", "path": str(self.tmp / "primes.txt"), "content": "SECRET-TOKEN"},
            True,
            "Wrote primes.txt",
        )
        tracker.record(
            "filesystem",
            {"action": "read", "path": str(self.tmp / "primes.txt")},
            True,
            "2 3 5",
        )
        first = record_trajectory(
            "Create a small Python program that writes 100 primes to primes.txt",
            tracker,
        )
        assert first is not None
        self.assertEqual(first.success_count, 1)
        self.assertFalse(first.stable)
        stored = json.loads((self.tmp / "trajectories.json").read_text(encoding="utf-8"))
        blob = json.dumps(stored)
        self.assertNotIn("SECRET-TOKEN", blob)
        self.assertNotIn("print(2)", blob)
        self.assertIn("primes.txt", blob)
        hint = format_trajectory_hint("Write the first 100 primes into primes.txt using a Python program")
        self.assertIn("python", hint)
        self.assertIn("filesystem write", hint)
        self.assertIn("Previous successful trajectories", hint)
        self.assertEqual(format_trajectory_hint("Look up the latest news on wikipedia"), "")

    def test_repeat_success_promotes_stable_and_keeps_recovery(self) -> None:
        tracker = CompletionTracker()
        tracker.record("terminal", {"action": "run", "command": "Get-Item C:\\missing"}, False, "ERROR: Path not found")
        tracker.record(
            "filesystem",
            {"action": "write", "path": str(self.tmp / "recovery.txt"), "content": "RECOVERED"},
            True,
            "Wrote recovery.txt",
        )
        prompt = "Use the terminal tool to run Get-Item C:\\missing then still write recovery.txt containing RECOVERED"
        first = record_trajectory(prompt, tracker)
        assert first is not None
        self.assertEqual(first.recovered_with, "filesystem")
        self.assertTrue(first.failures)
        second = record_trajectory(prompt, tracker)
        assert second is not None
        self.assertGreaterEqual(second.success_count, 2)
        self.assertTrue(second.stable)
        hint = format_trajectory_hint(prompt)
        self.assertIn("recovered with filesystem", hint)
        self.assertIn("failed terminal", hint)

    def test_unrelated_file_write_does_not_reuse_primes_trajectory(self) -> None:
        tracker = CompletionTracker()
        tracker.record(
            "filesystem",
            {"action": "write", "path": str(self.tmp / "primes.txt"), "content": "2"},
            True,
            "Wrote",
        )
        record_trajectory("Write primes.txt with a Python program listing primes", tracker)
        self.assertEqual(format_trajectory_hint("Create a folder on the desktop named Jarvis-Test and write notes.txt"), "")

    def test_store_is_capped(self) -> None:
        for i in range(MAX_TRAJECTORIES + 8):
            tracker = CompletionTracker()
            tracker.record("filesystem", {"action": "write", "path": str(self.tmp / f"t{i}.txt")}, True, "Wrote")
            record_trajectory(f"Write t{i}.txt with token {i}", tracker, task_class=f"slot{i}", worker="native")
        stored = json.loads((self.tmp / "trajectories.json").read_text(encoding="utf-8"))
        self.assertLessEqual(len(stored), MAX_TRAJECTORIES)

    def test_steps_from_tracker_sanitizes_paths_and_skips_failures_in_success_list(self) -> None:
        tracker = CompletionTracker()
        tracker.record("filesystem", {"action": "write", "path": r"C:\Users\daanv\secret\out.txt", "content": "nope"}, True, "Wrote")
        steps, failures, recovered = steps_from_tracker(tracker)
        self.assertEqual(steps[0]["target"], "out.txt")
        self.assertFalse(failures)
        self.assertEqual(recovered, "")
        self.assertNotIn("Users", json.dumps(steps))

    def test_disjoint_hosts_do_not_merge_or_reuse(self) -> None:
        tracker = CompletionTracker()
        tracker.record(
            "filesystem",
            {"action": "write", "path": str(self.tmp / "page-title.txt"), "content": "Example Domain"},
            True,
            "Wrote",
        )
        first = record_trajectory(
            "Open a browser, visit https://example.com, read the page title, and save that title to page-title.txt",
            tracker,
            task_class="browser",
            worker="native",
        )
        second = record_trajectory(
            "Open a browser, visit https://unfamiliar-intranet.test/admin, and save a report to page-title.txt",
            tracker,
            task_class="browser",
            worker="native",
        )
        assert first is not None and second is not None
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.success_count, 1)
        self.assertEqual(second.success_count, 1)
        stored = json.loads((self.tmp / "trajectories.json").read_text(encoding="utf-8"))
        self.assertEqual(len(stored), 2)
        hint = format_trajectory_hint(
            "Open a browser, visit https://unfamiliar-intranet.test/admin, and save a report",
            "browser",
        )
        self.assertNotIn("example.com", hint)

    def test_stable_same_class_does_not_reuse_without_distinctive_overlap(self) -> None:
        tracker = CompletionTracker()
        tracker.record("python", {"code": "print(2)", "path": str(self.tmp / "primes.py")}, True, "ok")
        tracker.record(
            "filesystem",
            {"action": "write", "path": str(self.tmp / "primes.txt"), "content": "2"},
            True,
            "Wrote",
        )
        prompt = "Create a small Python program that writes 100 primes to primes.txt"
        record_trajectory(prompt, tracker)
        record_trajectory(prompt, tracker)
        self.assertEqual(
            format_trajectory_hint("Find out why the Python project fails, fix it, and verify by running python main.py"),
            "",
        )
        self.assertIn("primes.txt", format_trajectory_hint("Write the first 100 primes into primes.txt using a Python program"))

    def test_optional_worker_steps_are_recorded(self) -> None:
        tracker = CompletionTracker()
        tracker.record(
            "browser_use",
            {"action": "run", "goal": "export a report", "url": "https://unfamiliar-intranet.test/admin"},
            True,
            "Discovered export",
        )
        tracker.record(
            "filesystem",
            {"action": "write", "path": str(self.tmp / "report.txt"), "content": "REPORT-OK"},
            True,
            "Wrote",
        )
        row = record_trajectory(
            "Open a browser, visit https://unfamiliar-intranet.test/admin, and export a report to report.txt",
            tracker,
            task_class="browser",
            worker="browser_use",
        )
        assert row is not None
        tools = [step.get("tool") for step in row.steps]
        self.assertIn("browser_use", tools)
        self.assertIn("filesystem", tools)
        self.assertEqual(row.steps[0].get("target"), "unfamiliar-intranet.test")


class TrajectoryLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t12-loop-"))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.settings = AppSettings(allowed_directories=[str(self.tmp)], autonomy="autonomous")
        REGISTRY.apply_settings(self.settings)
        self.patcher = patch(
            "app.agent.trajectories.trajectory_store_path",
            lambda: self.tmp / "trajectories.json",
        )
        self.skill_patcher = patch(
            "app.agent.skills.skill_store_path",
            lambda: self.tmp / "skills.json",
        )
        self.patcher.start()
        self.skill_patcher.start()

    async def asyncTearDown(self) -> None:
        self.skill_patcher.stop()
        self.patcher.stop()
        await self.engine.dispose()

    async def _noop(self, *args, **kwargs):
        return None

    async def test_second_similar_task_receives_trajectory_hint(self) -> None:
        first = self.tmp / "primes.txt"
        second = self.tmp / "primes.txt"
        runtime = AgentRuntime()
        manager_one = loop_manager(
            ScriptedProvider(
                [
                    ChatResult(
                        tool_calls=[
                            _tool_call("c1", "filesystem", {"action": "write", "path": str(first), "content": "2\n3\n5"})
                        ]
                    )
                ]
            ),
            profile="fast",
            thinking_at_process=False,
            record_timings=self._noop,
            load=self._noop,
        )
        prompt = f"Create a small Python program that writes 100 primes to {first}."
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.resume.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager_one),
            patch("app.agent.loop.load_settings", lambda: self.settings),
        ):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertEqual(stored.status, "completed")
        self.assertTrue((self.tmp / "trajectories.json").exists())

        provider = ScriptedProvider(
            [
                ChatResult(
                    tool_calls=[
                        _tool_call("c2", "filesystem", {"action": "write", "path": str(second), "content": "2\n3"})
                    ]
                )
            ]
        )
        manager_two = loop_manager(
            provider,
            profile="fast",
            thinking_at_process=False,
            record_timings=self._noop,
            load=self._noop,
        )
        follow = f"Create a small Python program that writes 100 primes to {second}."
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.resume.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager_two),
            patch("app.agent.loop.load_settings", lambda: self.settings),
        ):
            later = await runtime.create_task(follow, autonomy="autonomous", profile="fast")
            await runtime._tasks[later.id]
        blobs = [
            message.content if isinstance(message.content, str) else str(message.content)
            for message in provider.last_messages
            if message.role == "user"
        ]
        self.assertTrue(any("Previous successful trajectories" in blob for blob in blobs))
        self.assertTrue(any("filesystem write" in blob for blob in blobs))


if __name__ == "__main__":
    unittest.main()
