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

from app.agent.browser_workflows import (
    MAX_LEARNED_WORKFLOWS,
    format_workflow_hint,
    match_workflows,
    record_from_tracker,
    workflow_store_path,
)
from app.agent.completion import CompletionTracker
from app.agent.loop import AgentRuntime
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


class BrowserWorkflowLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t08-wf-"))
        self.patcher = patch(
            "app.agent.browser_workflows.workflow_store_path",
            lambda: self.tmp / "browser_workflows.json",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()

    def test_builtin_example_com_title_matches(self) -> None:
        prompt = "Open a browser, visit https://example.com, read the page title, and save it to page-title.txt"
        matches = match_workflows(prompt)
        self.assertTrue(matches)
        self.assertEqual(matches[0].id, "builtin-example-title")
        self.assertTrue(matches[0].stable)
        hint = format_workflow_hint(prompt)
        self.assertIn("save_title", hint)
        self.assertIn("example.com", hint)

    def test_unrelated_prompt_has_no_hint(self) -> None:
        self.assertEqual(format_workflow_hint("Write primes.txt with 100 primes"), "")

    def test_repeated_success_is_stored_and_promoted(self) -> None:
        tracker = CompletionTracker()
        tracker.record(
            "browser",
            {"action": "open", "url": "https://news.ycombinator.com"},
            True,
            "Opened",
        )
        tracker.record(
            "browser",
            {"action": "save_title", "url": "https://news.ycombinator.com", "path": str(self.tmp / "hn.txt")},
            True,
            "Wrote title",
        )
        prompt = "Save the Hacker News title from https://news.ycombinator.com to hn.txt"
        first = record_from_tracker(prompt, tracker)
        assert first is not None
        self.assertEqual(first.success_count, 1)
        self.assertFalse(first.stable)
        second = record_from_tracker(prompt, tracker)
        assert second is not None
        self.assertEqual(second.success_count, 2)
        self.assertTrue(second.stable)
        stored = json.loads((self.tmp / "browser_workflows.json").read_text(encoding="utf-8"))
        self.assertEqual(len(stored), 1)
        self.assertGreaterEqual(stored[0]["success_count"], 2)

    def test_learned_store_is_capped(self) -> None:
        for i in range(MAX_LEARNED_WORKFLOWS + 5):
            filled = CompletionTracker()
            filled.record(
                "browser",
                {"action": "open", "url": f"https://site{i}.example"},
                True,
                "Opened",
            )
            filled.record(
                "browser",
                {"action": "save_title", "url": f"https://site{i}.example", "path": str(self.tmp / f"t{i}.txt")},
                True,
                "Wrote title",
            )
            record_from_tracker(f"Save title from https://site{i}.example", filled)
        stored = json.loads((self.tmp / "browser_workflows.json").read_text(encoding="utf-8"))
        self.assertLessEqual(len(stored), MAX_LEARNED_WORKFLOWS)
        newest_tracker = CompletionTracker()
        newest_tracker.record(
            "browser",
            {"action": "open", "url": "https://brand-new.example"},
            True,
            "Opened",
        )
        newest = record_from_tracker("Save title from https://brand-new.example", newest_tracker)
        assert newest is not None
        stored = json.loads((self.tmp / "browser_workflows.json").read_text(encoding="utf-8"))
        ids = [row["id"] for row in stored]
        self.assertIn(newest.id, ids)
        self.assertLessEqual(len(stored), MAX_LEARNED_WORKFLOWS)


class BrowserWorkflowLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t08-loop-"))
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

    async def test_loop_injects_learned_example_com_hint(self) -> None:
        target = self.tmp / "page-title.txt"
        provider = ScriptedProvider(
            [
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c1",
                            "filesystem",
                            {"action": "write", "path": str(target), "content": "Example Domain"},
                        )
                    ]
                )
            ]
        )
        manager = loop_manager(
            provider,
            profile="fast",
            thinking_at_process=False,
            record_timings=self._noop,
            load=self._noop,
        )
        runtime = AgentRuntime()
        prompt = f"Open a browser, visit https://example.com, read the page title, and save that title to {target}."
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.resume.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager),
            patch("app.agent.loop.load_settings", lambda: self.settings),
        ):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        blobs = [
            message.content if isinstance(message.content, str) else str(message.content)
            for message in provider.last_messages
            if message.role == "user"
        ]
        self.assertTrue(any("save_title" in blob and "example.com" in blob for blob in blobs))
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertEqual(stored.status, "completed")


if __name__ == "__main__":
    unittest.main()
