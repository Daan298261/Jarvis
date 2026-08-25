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

from app.agent.loop import AgentRuntime
from app.agent.recovery import alternate_tools
from app.agent.routing import classify_task, list_workers, resolve_worker
from app.agent.workers.computer_use import cua_status, run_cua_task, run_ufo_task, ufo_status
from app.config import AppSettings
from app.db.models import Base, Task
from app.providers.base import ChatResult
from app.tools.cua import CuaTool
from app.tools.registry import REGISTRY
from app.tools.ufo import UFOTool

MISSING = {"available": False, "reason": "not installed", "version": ""}
UFO_OK = {"available": True, "reason": "Microsoft UFO is installed (mock)", "version": "mock"}
CUA_OK = {"available": True, "reason": "Cua is installed via cua_agent (mock)", "version": "mock", "module": "cua_agent"}
UNKNOWN_GUI = (
    "Use Calculator as a Windows GUI app via UI Automation. "
    "Click through the calculator window and save the displayed result to {path}."
)
NOTEPAD = "Use Notepad UI Automation to type JARVIS into a desktop app window and save the file."


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


class ComputerUseAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_status_unavailable_without_packages(self) -> None:
        with patch.dict(sys.modules, {"ufo": None, "cua_agent": None, "cua": None}):
            self.assertFalse(ufo_status()["available"])
            self.assertFalse(cua_status()["available"])
            self.assertIn("native UI Automation", ufo_status()["reason"] + cua_status()["reason"])

    async def test_run_degrades_when_missing(self) -> None:
        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: MISSING),
            patch("app.agent.workers.computer_use.cua_status", lambda: MISSING),
        ):
            ufo = await run_ufo_task("Click through Calculator")
            cua = await run_cua_task("Click through Calculator")
        self.assertFalse(ufo["success"])
        self.assertTrue(ufo["degraded"])
        self.assertIn("desktop", ufo["fallback"].lower() + " " + ufo["note"].lower())
        self.assertFalse(cua["success"])
        self.assertTrue(cua["degraded"])
        self.assertIn("pywinauto", cua["fallback"].lower())

    async def test_tools_status_and_run_when_missing(self) -> None:
        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: MISSING),
            patch("app.agent.workers.computer_use.cua_status", lambda: MISSING),
        ):
            ufo_status_result = await UFOTool().execute(action="status")
            ufo_run = await UFOTool().execute(action="run", goal="discover calculator", app="Calculator")
            cua_status_result = await CuaTool().execute(action="status")
            cua_run = await CuaTool().execute(action="run", goal="discover calculator", app="Calculator")
        self.assertTrue(ufo_status_result.success)
        self.assertFalse(ufo_run.success)
        self.assertIn("desktop", ufo_run.output.lower())
        self.assertTrue(cua_status_result.success)
        self.assertFalse(cua_run.success)
        self.assertIn("pywinauto", cua_run.output.lower())

    async def test_tools_run_when_available(self) -> None:
        async def fake_ufo(goal, app=None, max_steps=8):
            return {
                "success": True,
                "degraded": False,
                "worker": "ufo",
                "output": f"Clicked Calculator for {goal}",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator.",
            }

        async def fake_cua(goal, app=None, max_steps=8):
            return {
                "success": True,
                "degraded": False,
                "worker": "cua",
                "output": f"Used accessibility tree for {goal}",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator.",
            }

        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: UFO_OK),
            patch("app.agent.workers.computer_use.run_ufo_task", fake_ufo),
            patch("app.agent.workers.computer_use.cua_status", lambda: CUA_OK),
            patch("app.agent.workers.computer_use.run_cua_task", fake_cua),
        ):
            ufo = await UFOTool().execute(action="run", goal="read the display", app="Calculator")
            cua = await CuaTool().execute(action="run", goal="read the display", app="Calculator")
        self.assertTrue(ufo.success)
        self.assertEqual(ufo.data["worker"], "ufo")
        self.assertTrue(cua.success)
        self.assertEqual(cua.data["worker"], "cua")

    def test_unknown_gui_selects_ufo_when_available(self) -> None:
        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: UFO_OK),
            patch("app.agent.workers.computer_use.cua_status", lambda: MISSING),
        ):
            route = classify_task(UNKNOWN_GUI.format(path="calc-result.txt"))
            resolved = resolve_worker("ufo")
            workers = list_workers()
        self.assertEqual(route.task_class, "windows_gui")
        self.assertEqual(route.preferred_worker, "ufo")
        self.assertEqual(route.worker, "ufo")
        self.assertFalse(route.degraded)
        self.assertIn("ufo", route.offered_tools)
        self.assertIn("desktop", route.offered_tools)
        self.assertNotIn("cua", route.offered_tools)
        self.assertIn("orchestrator", route.prompt_hint().lower())
        self.assertEqual(resolved.name, "ufo")
        self.assertTrue([row for row in workers if row["name"] == "ufo"][0]["available"])

    def test_unknown_gui_falls_back_to_cua_then_native(self) -> None:
        prompt = UNKNOWN_GUI.format(path="calc-result.txt")
        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: MISSING),
            patch("app.agent.workers.computer_use.cua_status", lambda: CUA_OK),
        ):
            route = classify_task(prompt)
            self.assertEqual(resolve_worker("ufo").name, "cua")
        self.assertEqual(route.worker, "cua")
        self.assertEqual(route.preferred_worker, "ufo")
        self.assertTrue(route.degraded)
        self.assertIn("cua", route.offered_tools)
        self.assertNotIn("ufo", route.offered_tools)
        self.assertIn("using Cua", route.prompt_hint())

        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: MISSING),
            patch("app.agent.workers.computer_use.cua_status", lambda: MISSING),
        ):
            native = classify_task(prompt)
            self.assertEqual(resolve_worker("ufo").name, "native")
        self.assertEqual(native.worker, "native")
        self.assertTrue(native.degraded)
        self.assertNotIn("ufo", native.offered_tools)
        self.assertNotIn("cua", native.offered_tools)
        self.assertIn("UFO and Cua are unavailable", native.prompt_hint())

    def test_notepad_stays_native_even_when_workers_available(self) -> None:
        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: UFO_OK),
            patch("app.agent.workers.computer_use.cua_status", lambda: CUA_OK),
        ):
            route = classify_task(NOTEPAD)
        self.assertEqual(route.worker, "native")
        self.assertFalse(route.degraded)
        self.assertNotIn("ufo", route.offered_tools)
        self.assertIn("Known Windows UI workflow", route.prompt_hint())

    def test_catalog_includes_workers(self) -> None:
        names = {tool.name for tool in REGISTRY.tools.values()}
        self.assertIn("ufo", names)
        self.assertIn("cua", names)

    def test_recovery_falls_back_to_desktop(self) -> None:
        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: MISSING),
            patch("app.agent.workers.computer_use.cua_status", lambda: MISSING),
        ):
            self.assertNotIn("cua", alternate_tools("ufo"))
            self.assertNotIn("ufo", alternate_tools("desktop"))
            self.assertIn("desktop", alternate_tools("ufo"))
            self.assertIn("desktop", alternate_tools("cua"))
        with (
            patch("app.agent.workers.computer_use.ufo_status", lambda: UFO_OK),
            patch("app.agent.workers.computer_use.cua_status", lambda: CUA_OK),
        ):
            self.assertIn("cua", alternate_tools("ufo"))
            self.assertIn("desktop", alternate_tools("ufo"))
            self.assertIn("desktop", alternate_tools("cua"))


class ComputerUseLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t15-"))
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

    async def test_loop_uses_ufo_then_native_write(self) -> None:
        target = self.tmp / "calc-result.txt"

        async def fake_ufo(goal, app=None, max_steps=8):
            return {
                "success": True,
                "degraded": False,
                "worker": "ufo",
                "output": "Calculator display shows 19",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator. Prefer accessibility/UI Automation over coordinate clicking, then verify files with native tools.",
            }

        provider = ScriptedProvider(
            [
                ChatResult(
                    tool_calls=[
                        _tool_call("c1", "ufo", {"action": "run", "goal": "read Calculator display", "app": "Calculator"})
                    ]
                ),
                ChatResult(
                    tool_calls=[
                        _tool_call("c2", "filesystem", {"action": "write", "path": str(target), "content": "19"})
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
        prompt = UNKNOWN_GUI.format(path=target)
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.resume.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager),
            patch("app.agent.loop.load_settings", lambda: self.settings),
            patch("app.agent.workers.computer_use.ufo_status", lambda: UFO_OK),
            patch("app.agent.workers.computer_use.cua_status", lambda: MISSING),
            patch("app.agent.workers.computer_use.run_ufo_task", fake_ufo),
        ):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        self.assertEqual(task.task_class, "windows_gui")
        self.assertEqual(task.selected_worker, "ufo")
        names = _names(provider.last_tools)
        self.assertIn("ufo", names)
        self.assertIn("desktop", names)
        self.assertNotIn("office", names)
        blobs = [
            message.content if isinstance(message.content, str) else str(message.content)
            for message in provider.last_messages
            if message.role == "user"
        ]
        self.assertTrue(any("orchestrator" in blob.lower() for blob in blobs))
        self.assertEqual(target.read_text(encoding="utf-8").strip(), "19")
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertEqual(stored.selected_worker, "ufo")
        self.assertEqual(stored.status, "completed")


if __name__ == "__main__":
    unittest.main()
