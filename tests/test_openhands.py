from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from manager_mock import loop_manager, noop

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.loop import AgentRuntime
from app.agent.recovery import alternate_tools
from app.agent.routing import classify_task, large_repo_work, list_workers, resolve_worker
from app.agent.workers.openhands import openhands_status, run_openhands_task
from app.config import AppSettings
from app.db.models import Base, Task
from app.providers.base import ChatResult
from app.tools.openhands import OpenHandsTool
from app.tools.registry import REGISTRY

UNAVAILABLE = {
    "available": False,
    "reason": "OpenHands is not installed; using filesystem/python/git",
    "version": "",
    "cli": False,
    "sdk": False,
}
AVAILABLE = {
    "available": True,
    "reason": "OpenHands is installed (CLI + SDK) mock",
    "version": "mock",
    "cli": True,
    "sdk": True,
}
SMALL_PRIMES = (
    "Create a small Python program that calculates the first 100 prime numbers, run it, and save the result "
    "to primes.txt."
)
LARGE_REPO = (
    "Refactor the entire repository at {path}: apply a large multi-file cleanup across the codebase, "
    "then run the test suite and save the verification result to {verify}."
)


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _names(schemas: list[dict]) -> set[str]:
    return {(schema.get("function") or {}).get("name") or "" for schema in schemas}


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


class OpenHandsAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_status_unavailable_without_package(self) -> None:
        dummy = types.ModuleType("openhands")
        dummy.helper = True
        with (
            patch.dict(
                sys.modules,
                {"openhands": dummy, "openhands.sdk": None, "openhands_sdk": None, "openhands.core": None},
            ),
            patch("app.agent.workers.openhands.shutil.which", return_value=None),
            patch.dict(os.environ, {"JARVIS_OPENHANDS": "1", "JARVIS_OPENHANDS_BIN": ""}, clear=False),
        ):
            status = openhands_status()
        self.assertFalse(status["available"])
        self.assertIn("filesystem/python/git", status["reason"])

    def test_status_rejects_unrelated_openhands_module(self) -> None:
        dummy = types.ModuleType("openhands")
        dummy.LLM = object
        dummy.Session = object
        with (
            patch.dict(
                sys.modules,
                {"openhands": dummy, "openhands.sdk": None, "openhands_sdk": None, "openhands.core": None},
            ),
            patch("app.agent.workers.openhands.shutil.which", return_value=None),
            patch.dict(os.environ, {"JARVIS_OPENHANDS": "1", "JARVIS_OPENHANDS_BIN": ""}, clear=False),
        ):
            status = openhands_status()
        self.assertFalse(status["available"])

    def test_disabled_by_env(self) -> None:
        with patch.dict(os.environ, {"JARVIS_OPENHANDS": "0"}, clear=False):
            status = openhands_status()
        self.assertFalse(status["available"])
        self.assertIn("JARVIS_OPENHANDS", status["reason"])

    async def test_run_degrades_when_missing(self) -> None:
        with patch("app.agent.workers.openhands.openhands_status", lambda: UNAVAILABLE):
            result = await run_openhands_task("Refactor the entire repository", path="C:\\repo")
        self.assertFalse(result["success"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["worker"], "native")
        self.assertIn("filesystem", result["fallback"].lower())
        self.assertIn("orchestrator", result["note"].lower())
        self.assertIn("verif", result["note"].lower())

    async def test_tool_status_and_run_when_missing(self) -> None:
        tool = OpenHandsTool()
        with patch("app.agent.workers.openhands.openhands_status", lambda: UNAVAILABLE):
            status = await tool.execute(action="status")
            run = await tool.execute(action="run", goal="refactor the entire repository", path="C:\\repo")
        self.assertTrue(status.success)
        self.assertIn("filesystem", status.output.lower())
        self.assertFalse(run.success)
        self.assertIn("python", run.output.lower())
        self.assertIn("orchestrator", run.output.lower())

    async def test_tool_run_when_available_returns_worker_output(self) -> None:
        async def fake_run(goal, path=None, max_steps=12):
            return {
                "success": True,
                "degraded": False,
                "worker": "openhands",
                "output": f"Refactored {path} for {goal}",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator. After OpenHands returns, inspect and test.",
            }

        tmp = Path(tempfile.mkdtemp(prefix="jarvis-t16-tool-"))
        tool = OpenHandsTool(lambda: {"allowed_directories": [str(tmp)]})
        with (
            patch("app.agent.workers.openhands.openhands_status", lambda: AVAILABLE),
            patch("app.agent.workers.openhands.run_openhands_task", fake_run),
        ):
            result = await tool.execute(action="run", goal="large multi-file cleanup", path=str(tmp))
        self.assertTrue(result.success)
        self.assertIn("Refactored", result.output)
        self.assertIn("orchestrator", result.output.lower())
        self.assertEqual(result.data["worker"], "openhands")

    async def test_cli_invocation_when_available(self) -> None:
        class FakeProc:
            returncode = 0

            async def communicate(self):
                return b"cleaned 12 files across the codebase", b""

            def kill(self):
                pass

            async def wait(self):
                return 0

        async def fake_exec(*args, **kwargs):
            return FakeProc()

        status = {**AVAILABLE, "sdk": False}
        with (
            patch("app.agent.workers.openhands.openhands_status", lambda: status),
            patch("app.agent.workers.openhands._cli_path", lambda: "openhands.exe"),
            patch("app.agent.workers.openhands._llm_env", lambda: os.environ.copy()),
            patch("asyncio.create_subprocess_exec", fake_exec),
        ):
            result = await run_openhands_task("Refactor the entire repository", path="C:\\repo")
        self.assertTrue(result["success"])
        self.assertEqual(result["worker"], "openhands")
        self.assertIn("12 files", result["output"])
        self.assertIn("verif", result["note"].lower())

    def test_large_repo_selects_worker_when_available(self) -> None:
        prompt = LARGE_REPO.format(path="C:\\src\\app", verify="verify.txt")
        self.assertTrue(large_repo_work(prompt))
        with patch("app.agent.workers.openhands.openhands_status", lambda: AVAILABLE):
            route = classify_task(prompt)
            workers = list_workers()
            resolved = resolve_worker("openhands")
        self.assertEqual(route.task_class, "software_engineering")
        self.assertEqual(route.preferred_worker, "openhands")
        self.assertEqual(route.worker, "openhands")
        self.assertFalse(route.degraded)
        self.assertIn("openhands", route.offered_tools)
        self.assertIn("python", route.offered_tools)
        self.assertIn("filesystem", route.offered_tools)
        self.assertIn("git", route.offered_tools)
        self.assertIn("Large repository work", route.prompt_hint())
        self.assertIn("verif", route.prompt_hint().lower())
        self.assertEqual(resolved.name, "openhands")
        row = [item for item in workers if item["name"] == "openhands"][0]
        self.assertTrue(row["available"])

    def test_large_repo_degrades_when_missing(self) -> None:
        prompt = LARGE_REPO.format(path="C:\\src\\app", verify="verify.txt")
        with patch("app.agent.workers.openhands.openhands_status", lambda: UNAVAILABLE):
            route = classify_task(prompt)
            self.assertEqual(resolve_worker("openhands").name, "native")
        self.assertEqual(route.task_class, "software_engineering")
        self.assertEqual(route.preferred_worker, "openhands")
        self.assertEqual(route.worker, "native")
        self.assertTrue(route.degraded)
        self.assertNotIn("openhands", route.offered_tools)
        self.assertIn("OpenHands is unavailable", route.prompt_hint())

    def test_small_primes_stays_native_even_when_worker_available(self) -> None:
        self.assertFalse(large_repo_work(SMALL_PRIMES))
        with patch("app.agent.workers.openhands.openhands_status", lambda: AVAILABLE):
            route = classify_task(SMALL_PRIMES)
        self.assertEqual(route.task_class, "software_engineering")
        self.assertEqual(route.worker, "native")
        self.assertEqual(route.preferred_worker, "native")
        self.assertFalse(route.degraded)
        self.assertNotIn("openhands", route.offered_tools)
        self.assertIn("native_coding_tools", route.reason)
        self.assertIn("Small coding job", route.prompt_hint())

    def test_catalog_includes_openhands_tool(self) -> None:
        names = {tool.name for tool in REGISTRY.tools.values()}
        self.assertIn("openhands", names)

    def test_recovery_falls_back_to_native_coding_tools(self) -> None:
        with patch("app.agent.workers.openhands.openhands_status", lambda: UNAVAILABLE):
            alts = alternate_tools("openhands")
            self.assertIn("filesystem", alts)
            self.assertIn("python", alts)
            self.assertIn("git", alts)
            self.assertNotIn("openhands", alternate_tools("python"))
        with patch("app.agent.workers.openhands.openhands_status", lambda: AVAILABLE):
            self.assertIn("openhands", alternate_tools("python"))
            self.assertIn("python", alternate_tools("openhands"))
            self.assertIn("git", alternate_tools("openhands"))


class OpenHandsLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t16-"))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.settings = AppSettings(allowed_directories=[str(self.tmp)], autonomy="autonomous")
        REGISTRY.apply_settings(self.settings)
        self._store_patches = [
            patch("app.agent.trajectories.trajectory_store_path", lambda: self.tmp / "trajectories.json"),
            patch("app.agent.skills.skill_store_path", lambda: self.tmp / "skills.json"),
            patch("app.agent.browser_workflows.workflow_store_path", lambda: self.tmp / "browser_workflows.json"),
        ]
        for item in self._store_patches:
            item.start()

    async def asyncTearDown(self) -> None:
        for item in reversed(self._store_patches):
            item.stop()
        await self.engine.dispose()

    async def _noop(self, *args, **kwargs):
        return None

    async def test_loop_uses_worker_then_native_verify(self) -> None:
        verify = self.tmp / "verify.txt"

        async def fake_run(goal, path=None, max_steps=12):
            return {
                "success": True,
                "degraded": False,
                "worker": "openhands",
                "output": "Refactored 18 files and reported TESTS-OK",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator. After OpenHands returns, inspect, test, and verify.",
            }

        provider = ScriptedProvider(
            [
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c1",
                            "openhands",
                            {
                                "action": "run",
                                "goal": "large multi-file cleanup across the codebase",
                                "path": str(self.tmp),
                            },
                        )
                    ]
                ),
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c2",
                            "python",
                            {"action": "run_code", "code": "print('TESTS-OK')"},
                        )
                    ]
                ),
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c3",
                            "filesystem",
                            {"action": "write", "path": str(verify), "content": "TESTS-OK"},
                        )
                    ]
                ),
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
        prompt = LARGE_REPO.format(path=self.tmp, verify=verify)
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.resume.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager),
            patch("app.agent.loop.load_settings", lambda: self.settings),
            patch("app.agent.workers.openhands.openhands_status", lambda: AVAILABLE),
            patch("app.agent.workers.openhands.run_openhands_task", fake_run),
        ):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        self.assertEqual(task.task_class, "software_engineering")
        self.assertEqual(task.selected_worker, "openhands")
        names = _names(provider.last_tools)
        self.assertIn("openhands", names)
        self.assertIn("python", names)
        self.assertIn("filesystem", names)
        self.assertIn("git", names)
        self.assertNotIn("office", names)
        blobs = [
            message.content if isinstance(message.content, str) else str(message.content)
            for message in provider.last_messages
            if message.role == "user"
        ]
        self.assertTrue(any("Large repository work" in blob and "verif" in blob.lower() for blob in blobs))
        self.assertTrue(verify.exists())
        self.assertEqual(verify.read_text(encoding="utf-8").strip(), "TESTS-OK")
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertEqual(stored.selected_worker, "openhands")
        self.assertEqual(stored.status, "completed")


if __name__ == "__main__":
    unittest.main()
