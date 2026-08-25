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
from app.agent.routing import classify_task, interpreter_session, list_workers, resolve_worker
from app.agent.workers.open_interpreter import open_interpreter_status, run_open_interpreter_task
from app.config import AppSettings
from app.db.models import Base, Task
from app.providers.base import ChatResult
from app.tools.open_interpreter import OpenInterpreterTool
from app.tools.registry import REGISTRY

UNAVAILABLE = {
    "available": False,
    "reason": "Open Interpreter is not installed; using the python tool",
    "version": "",
    "cli": False,
    "sdk": False,
}
AVAILABLE = {
    "available": True,
    "reason": "Open Interpreter is installed (SDK) mock",
    "version": "mock",
    "cli": False,
    "sdk": True,
}
SMALL_PRIMES = (
    "Create a small Python program that calculates the first 100 prime numbers, run it, and save the result "
    "to primes.txt."
)
INTERPRETER = (
    "Use Open Interpreter in an interactive Python REPL to explore the environment and experiment "
    "with the interpreter, then save what you learned to {path}."
)


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _names(schemas: list[dict]) -> set[str]:
    return {(schema.get("function") or {}).get("name") or "" for schema in schemas}


def _ordered_names(schemas: list[dict]) -> list[str]:
    return [(schema.get("function") or {}).get("name") or "" for schema in schemas]


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


class OpenInterpreterAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_status_unavailable_without_package(self) -> None:
        dummy = types.ModuleType("interpreter")
        dummy.helper = True
        with (
            patch.dict(
                sys.modules,
                {
                    "interpreter": dummy,
                    "openinterpreter": None,
                    "interpreter.core.open_interpreter": None,
                    "interpreter.core.core": None,
                },
            ),
            patch("app.agent.workers.open_interpreter._cli_path", lambda: ""),
            patch.dict(os.environ, {"JARVIS_OPEN_INTERPRETER": "1", "JARVIS_OPEN_INTERPRETER_BIN": ""}, clear=False),
        ):
            status = open_interpreter_status()
        self.assertFalse(status["available"])
        self.assertIn("python tool", status["reason"])

    def test_generic_interpreter_binary_is_not_open_interpreter(self) -> None:
        dummy = types.ModuleType("interpreter")
        dummy.helper = True

        def fake_which(name: str) -> str:
            return r"C:\Windows\interpreter.exe" if name == "interpreter" else ""

        with (
            patch.dict(
                sys.modules,
                {
                    "interpreter": dummy,
                    "openinterpreter": None,
                    "interpreter.core.open_interpreter": None,
                    "interpreter.core.core": None,
                },
            ),
            patch("app.agent.workers.open_interpreter.shutil.which", fake_which),
            patch.dict(os.environ, {"JARVIS_OPEN_INTERPRETER": "1", "JARVIS_OPEN_INTERPRETER_BIN": ""}, clear=False),
        ):
            status = open_interpreter_status()
        self.assertFalse(status["available"])

    def test_disabled_by_env(self) -> None:
        with patch.dict(os.environ, {"JARVIS_OPEN_INTERPRETER": "0"}, clear=False):
            status = open_interpreter_status()
        self.assertFalse(status["available"])
        self.assertIn("JARVIS_OPEN_INTERPRETER", status["reason"])

    async def test_run_degrades_when_missing(self) -> None:
        with patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: UNAVAILABLE):
            result = await run_open_interpreter_task("Explore the Python environment")
        self.assertFalse(result["success"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["worker"], "native")
        self.assertIn("python", result["fallback"].lower())
        self.assertIn("native", result["fallback"].lower())
        self.assertIn("orchestrator", result["note"].lower())

    async def test_tool_status_and_run_when_missing(self) -> None:
        tool = OpenInterpreterTool()
        with patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: UNAVAILABLE):
            status = await tool.execute(action="status")
            run = await tool.execute(action="run", goal="explore the python environment")
        self.assertTrue(status.success)
        self.assertIn("python", status.output.lower())
        self.assertFalse(run.success)
        self.assertIn("python", run.output.lower())
        self.assertIn("orchestrator", run.output.lower())

    async def test_tool_run_when_available_returns_worker_output(self) -> None:
        async def fake_run(goal, path=None, max_steps=8):
            return {
                "success": True,
                "degraded": False,
                "worker": "open_interpreter",
                "output": f"Explored {path} for {goal}",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator. Native python stays first.",
            }

        tmp = Path(tempfile.mkdtemp(prefix="jarvis-t17-tool-"))
        tool = OpenInterpreterTool(lambda: {"allowed_directories": [str(tmp)]})
        with (
            patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: AVAILABLE),
            patch("app.agent.workers.open_interpreter.run_open_interpreter_task", fake_run),
        ):
            result = await tool.execute(action="run", goal="interactive python repl", path=str(tmp))
        self.assertTrue(result.success)
        self.assertIn("Explored", result.output)
        self.assertIn("orchestrator", result.output.lower())
        self.assertEqual(result.data["worker"], "open_interpreter")

    async def test_sdk_chat_when_available(self) -> None:
        class FakeInterpreter:
            llm = SimpleNamespace()
            auto_run = False
            offline = False
            custom_instructions = ""

            def chat(self, message, display=False, blocking=True):
                return [{"role": "computer", "content": f"REPL said {message}"}]

        fake_pkg = SimpleNamespace(OpenInterpreter=lambda: FakeInterpreter(), __version__="mock")
        with (
            patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: AVAILABLE),
            patch("app.agent.workers.open_interpreter._package", lambda: fake_pkg),
            patch("app.agent.workers.open_interpreter._configure", lambda inst: None),
        ):
            result = await run_open_interpreter_task("explore sys.version")
        self.assertTrue(result["success"])
        self.assertEqual(result["worker"], "open_interpreter")
        self.assertIn("sys.version", result["output"])
        self.assertIn("native", result["note"].lower())

    def test_interpreter_session_selects_worker_when_available(self) -> None:
        prompt = INTERPRETER.format(path="notes.txt")
        self.assertTrue(interpreter_session(prompt))
        with patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: AVAILABLE):
            route = classify_task(prompt)
            workers = list_workers()
            resolved = resolve_worker("open_interpreter")
        self.assertIn(route.task_class, {"software_engineering", "mixed", "data"})
        self.assertEqual(route.preferred_worker, "open_interpreter")
        self.assertEqual(route.worker, "open_interpreter")
        self.assertFalse(route.degraded)
        self.assertIn("open_interpreter", route.offered_tools)
        self.assertIn("python", route.offered_tools)
        self.assertIn("filesystem", route.offered_tools)
        self.assertLess(route.offered_tools.index("python"), route.offered_tools.index("open_interpreter"))
        self.assertEqual(route.preferred_tools[0], "python")
        self.assertIn("Native python", route.prompt_hint())
        self.assertIn("orchestrator", route.prompt_hint().lower())
        self.assertEqual(resolved.name, "open_interpreter")
        row = [item for item in workers if item["name"] == "open_interpreter"][0]
        self.assertTrue(row["available"])

    def test_interpreter_session_degrades_when_missing(self) -> None:
        prompt = INTERPRETER.format(path="notes.txt")
        with patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: UNAVAILABLE):
            route = classify_task(prompt)
            self.assertEqual(resolve_worker("open_interpreter").name, "native")
        self.assertEqual(route.preferred_worker, "open_interpreter")
        self.assertEqual(route.worker, "native")
        self.assertTrue(route.degraded)
        self.assertNotIn("open_interpreter", route.offered_tools)
        self.assertIn("python", route.offered_tools)
        self.assertIn("Open Interpreter is unavailable", route.prompt_hint())
        self.assertIn("native python", route.prompt_hint().lower())

    def test_small_primes_stays_native_even_when_worker_available(self) -> None:
        self.assertFalse(interpreter_session(SMALL_PRIMES))
        with patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: AVAILABLE):
            route = classify_task(SMALL_PRIMES)
        self.assertEqual(route.task_class, "software_engineering")
        self.assertEqual(route.worker, "native")
        self.assertEqual(route.preferred_worker, "native")
        self.assertFalse(route.degraded)
        self.assertNotIn("open_interpreter", route.offered_tools)
        self.assertIn("python", route.offered_tools)
        self.assertIn("native_coding_tools", route.reason)
        self.assertIn("Do not use OpenHands or Open Interpreter", route.prompt_hint())

    def test_catalog_includes_open_interpreter_tool(self) -> None:
        names = {tool.name for tool in REGISTRY.tools.values()}
        self.assertIn("open_interpreter", names)

    def test_recovery_falls_back_to_python(self) -> None:
        with patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: UNAVAILABLE):
            alts = alternate_tools("open_interpreter")
            self.assertIn("python", alts)
            self.assertIn("filesystem", alts)
            self.assertNotIn("open_interpreter", alternate_tools("python"))
        with patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: AVAILABLE):
            self.assertIn("open_interpreter", alternate_tools("python"))
            self.assertIn("python", alternate_tools("open_interpreter"))


class OpenInterpreterLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t17-"))
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

    async def test_loop_keeps_native_tools_first_then_verifies(self) -> None:
        notes = self.tmp / "oi-notes.txt"

        async def fake_run(goal, path=None, max_steps=8):
            return {
                "success": True,
                "degraded": False,
                "worker": "open_interpreter",
                "output": "REPL explored sys.version; LEARNED-OK",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator. Native python, filesystem, and terminal stay first.",
            }

        provider = ScriptedProvider(
            [
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c1",
                            "python",
                            {"action": "run_code", "code": "print('native-first')"},
                        )
                    ]
                ),
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c2",
                            "open_interpreter",
                            {
                                "action": "run",
                                "goal": "interactive python repl explore the environment",
                                "path": str(self.tmp),
                            },
                        )
                    ]
                ),
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c3",
                            "filesystem",
                            {"action": "write", "path": str(notes), "content": "LEARNED-OK"},
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
        prompt = INTERPRETER.format(path=notes)
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.resume.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager),
            patch("app.agent.loop.load_settings", lambda: self.settings),
            patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: AVAILABLE),
            patch("app.agent.workers.open_interpreter.run_open_interpreter_task", fake_run),
        ):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        self.assertEqual(task.selected_worker, "open_interpreter")
        names = _names(provider.last_tools)
        ordered = _ordered_names(provider.last_tools)
        self.assertIn("open_interpreter", names)
        self.assertIn("python", names)
        self.assertIn("filesystem", names)
        self.assertLess(ordered.index("python"), ordered.index("open_interpreter"))
        self.assertNotIn("office", names)
        blobs = [
            message.content if isinstance(message.content, str) else str(message.content)
            for message in provider.last_messages
            if message.role == "user"
        ]
        self.assertTrue(any("Native python" in blob and "orchestrator" in blob.lower() for blob in blobs))
        self.assertTrue(notes.exists())
        self.assertEqual(notes.read_text(encoding="utf-8").strip(), "LEARNED-OK")
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertEqual(stored.selected_worker, "open_interpreter")
        self.assertEqual(stored.status, "completed")


if __name__ == "__main__":
    unittest.main()
