from __future__ import annotations

import asyncio
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

    async def chat(self, messages, tools=None, **kwargs) -> ChatResult:
        self.calls += 1
        self.thinking.append(kwargs.get("thinking"))
        if self.calls > len(self.results):
            raise AssertionError(f"Loop kept calling the model after completion evidence (call {self.calls})")
        return self.results[self.calls - 1]


class AgentLoopCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t01-"))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.settings = AppSettings(allowed_directories=[str(self.tmp)], autonomy="autonomous")
        REGISTRY.apply_settings(self.settings)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _run_script(self, prompt: str, results: list[ChatResult]) -> tuple[Task, ScriptedProvider]:
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
            return stored, provider

    async def _noop(self, *args, **kwargs):
        return None

    async def test_write_then_read_marks_task_completed_without_extra_model_round(self) -> None:
        target = self.tmp / "smoke.txt"
        prompt = f"Write READY to {target} and verify the file."
        results = [
            ChatResult(
                tool_calls=[
                    _tool_call("c1", "filesystem", {"action": "write", "path": str(target), "content": "READY"}),
                ]
            ),
            ChatResult(
                tool_calls=[
                    _tool_call("c2", "filesystem", {"action": "read", "path": str(target)}),
                ]
            ),
        ]
        stored, provider = await self._run_script(prompt, results)
        self.assertEqual(stored.status, "completed")
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "READY")
        self.assertEqual(provider.calls, 1)
        self.assertIn("READY", stored.result)
        self.assertTrue(stored.finished_at)
        self.assertIn("Independent verification", stored.result)
        self.assertIn("ok", (stored.verification or "").lower())

    async def test_write_then_list_poll_completes_without_final_report_generation(self) -> None:
        target = self.tmp / "out.txt"
        prompt = f"Create {target} containing hello."
        results = [
            ChatResult(
                tool_calls=[
                    _tool_call("c1", "filesystem", {"action": "write", "path": str(target), "content": "hello"}),
                ]
            ),
            ChatResult(
                tool_calls=[
                    _tool_call("c2", "filesystem", {"action": "list", "path": str(self.tmp)}),
                ]
            ),
            ChatResult(
                tool_calls=[
                    _tool_call("c3", "filesystem", {"action": "list", "path": str(self.tmp)}),
                ]
            ),
        ]
        stored, provider = await self._run_script(prompt, results)
        self.assertEqual(stored.status, "completed")
        self.assertEqual(target.read_text(encoding="utf-8"), "hello")
        self.assertEqual(provider.calls, 1)
        self.assertIn("Independent verification", stored.result)

    async def test_failed_independent_verify_repairs_without_thinking_pass(self) -> None:
        from app.agent.verify import Check, VerificationResult

        target = self.tmp / "out.txt"
        prompt = f"Create {target} containing hello."
        results = [
            ChatResult(
                tool_calls=[
                    _tool_call("c1", "filesystem", {"action": "write", "path": str(target), "content": "hello"}),
                ]
            ),
            ChatResult(
                tool_calls=[
                    _tool_call("c2", "filesystem", {"action": "list", "path": str(self.tmp)}),
                ]
            ),
            ChatResult(
                tool_calls=[
                    _tool_call("c3", "filesystem", {"action": "list", "path": str(self.tmp)}),
                ]
            ),
            ChatResult(content="done after repair"),
        ]
        calls = {"n": 0}

        def fake_inspect(tracker, user_prompt=""):
            calls["n"] += 1
            if calls["n"] == 1:
                return VerificationResult(ok=False, checks=[Check(str(target), False, "path does not exist")])
            return VerificationResult(ok=True, checks=[Check(str(target), True, "exists (5 bytes)")])

        provider = ScriptedProvider(results)
        manager = loop_manager(provider, record_timings=noop, load=noop)
        runtime = AgentRuntime()
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager),
            patch("app.agent.loop.load_settings", lambda: self.settings),
            patch("app.agent.loop.inspect_artifacts", fake_inspect),
        ):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="balanced")
            await runtime._tasks[task.id]
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertEqual(stored.status, "completed")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(provider.thinking[0], True)
        self.assertEqual(provider.thinking[-1], False)
        self.assertIn("Independent verification", stored.result)


if __name__ == "__main__":
    unittest.main()
