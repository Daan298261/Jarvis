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

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.loop import AgentRuntime
from app.agent.routing import classify_task, list_workers, resolve_worker
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


class TaskClassificationTests(unittest.TestCase):
    def test_known_example_com_stays_on_playwright(self) -> None:
        route = classify_task(
            "Open a browser, visit https://example.com, read the page title, and save that title to page-title.txt"
        )
        self.assertEqual(route.task_class, "browser")
        self.assertIn("browser", route.preferred_tools)
        self.assertIn("web_fetch", route.offered_tools)
        self.assertNotIn("office", route.offered_tools)
        self.assertNotIn("browser_use", route.offered_tools)
        self.assertEqual(route.preferred_worker, "native")
        self.assertEqual(route.worker, "native")
        self.assertFalse(route.degraded)
        self.assertIn("known_playwright_workflow", route.reason)
        self.assertIn("Known website workflow", route.prompt_hint())

    def test_unknown_site_prefers_browser_use_and_degrades_when_missing(self) -> None:
        prompt = (
            "Open a browser, visit https://unfamiliar-intranet.test/admin, "
            "and click through the unknown dashboard to export a report."
        )
        with patch(
            "app.agent.workers.browser_use.browser_use_status",
            lambda: {"available": False, "reason": "browser-use package is not installed; using Playwright", "version": ""},
        ):
            route = classify_task(prompt)
        self.assertEqual(route.task_class, "browser")
        self.assertEqual(route.preferred_worker, "browser_use")
        self.assertEqual(route.worker, "native")
        self.assertTrue(route.degraded)
        self.assertNotIn("browser_use", route.offered_tools)
        self.assertIn("Browser Use is unavailable", route.prompt_hint())

    def test_notepad_gui_stays_on_native_desktop(self) -> None:
        route = classify_task("Use Notepad UI Automation to type JARVIS into a desktop app window and save the file.")
        self.assertEqual(route.task_class, "windows_gui")
        self.assertIn("desktop", route.preferred_tools)
        self.assertNotIn("ufo", route.offered_tools)
        self.assertNotIn("cua", route.offered_tools)
        self.assertEqual(route.preferred_worker, "native")
        self.assertEqual(route.worker, "native")
        self.assertFalse(route.degraded)
        self.assertIn("known_pywinauto_workflow", route.reason)
        self.assertIn("Known Windows UI workflow", route.prompt_hint())

    def test_folder_on_desktop_is_filesystem_not_gui(self) -> None:
        route = classify_task(
            "Create a folder on the desktop named Jarvis-Test and write a text file named notes.txt containing hello."
        )
        self.assertEqual(route.task_class, "filesystem")
        self.assertIn("filesystem", route.preferred_tools)
        self.assertNotIn("desktop", route.preferred_tools)

    def test_system_specs_uses_system_info(self) -> None:
        route = classify_task(
            "Create a folder on the desktop named Jarvis-Test and write a text file named system-specs.txt "
            "containing the current system specifications (OS, CPU, RAM, GPU, VRAM)."
        )
        self.assertEqual(route.task_class, "system_admin")
        self.assertIn("system_info", route.preferred_tools)
        self.assertIn("filesystem", route.offered_tools)

    def test_python_program_is_software_engineering(self) -> None:
        route = classify_task(
            "Create a small Python program that calculates the first 100 prime numbers, run it, and save the result "
            "to primes.txt."
        )
        self.assertEqual(route.task_class, "software_engineering")
        self.assertIn("python", route.offered_tools)
        self.assertIn("filesystem", route.offered_tools)
        self.assertEqual(route.preferred_worker, "native")
        self.assertEqual(route.worker, "native")
        self.assertFalse(route.degraded)
        self.assertNotIn("openhands", route.offered_tools)
        self.assertNotIn("open_interpreter", route.offered_tools)
        self.assertIn("native_coding_tools", route.reason)

    def test_broken_project_is_software_engineering(self) -> None:
        route = classify_task("Find out why the Python project fails, fix it, and verify by running python main.py.")
        self.assertEqual(route.task_class, "software_engineering")
        self.assertIn("git", route.offered_tools)
        self.assertEqual(route.worker, "native")
        self.assertFalse(route.degraded)
        self.assertNotIn("openhands", route.offered_tools)

    def test_vision_is_multimodal(self) -> None:
        route = classify_task(
            "Look at this image: C:\\tmp\\vision-target.png. Identify the visible text and the color of the circle."
        )
        self.assertEqual(route.task_class, "multimodal")
        self.assertIn("screenshot", route.offered_tools)
        self.assertIn("filesystem", route.offered_tools)

    def test_terminal_recovery_is_shell_and_keeps_filesystem_fallback(self) -> None:
        route = classify_task(
            "Use the terminal tool to run the PowerShell command Get-Item C:\\missing. "
            "It will fail. Recover and still write recovery.txt containing RECOVERED."
        )
        self.assertEqual(route.task_class, "shell")
        self.assertIn("terminal", route.preferred_tools)
        self.assertIn("filesystem", route.offered_tools)
        self.assertIn("python", route.offered_tools)

    def test_excel_routes_to_office(self) -> None:
        route = classify_task("Create an Excel workbook named report.xlsx with a revenue spreadsheet.")
        self.assertEqual(route.task_class, "office")
        self.assertIn("office", route.preferred_tools)

    def test_unknown_prompt_is_mixed_and_offers_core_tools(self) -> None:
        route = classify_task("Please help.")
        self.assertEqual(route.task_class, "mixed")
        self.assertIn("filesystem", route.offered_tools)
        self.assertIn("browser", route.offered_tools)

    def test_unavailable_workers_degrade_to_native(self) -> None:
        missing = {"available": False, "reason": "not installed", "version": ""}
        with (
            patch("app.agent.workers.browser_use.browser_use_status", lambda: missing),
            patch("app.agent.workers.computer_use.ufo_status", lambda: missing),
            patch("app.agent.workers.computer_use.cua_status", lambda: missing),
            patch("app.agent.workers.openhands.openhands_status", lambda: missing),
            patch("app.agent.workers.open_interpreter.open_interpreter_status", lambda: missing),
        ):
            self.assertEqual(resolve_worker("browser_use").name, "native")
            self.assertEqual(resolve_worker("ufo").name, "native")
            self.assertEqual(resolve_worker("cua").name, "native")
            self.assertEqual(resolve_worker("openhands").name, "native")
            self.assertEqual(resolve_worker("open_interpreter").name, "native")
            self.assertFalse([row for row in list_workers() if row["name"] == "browser_use"][0]["available"])
            self.assertFalse([row for row in list_workers() if row["name"] == "ufo"][0]["available"])
            self.assertFalse([row for row in list_workers() if row["name"] == "cua"][0]["available"])
            self.assertFalse([row for row in list_workers() if row["name"] == "openhands"][0]["available"])
            self.assertFalse([row for row in list_workers() if row["name"] == "open_interpreter"][0]["available"])
        native = [row for row in list_workers() if row["name"] == "native"][0]
        self.assertTrue(native["available"])

    def test_browser_schemas_exclude_office(self) -> None:
        route = classify_task("Open a browser and visit https://example.com for the page title")
        schemas = [
            {"type": "function", "function": {"name": name}}
            for name in ("filesystem", "browser", "web_fetch", "office", "docker", "desktop")
        ]
        names = _names(route.filter_schemas(schemas))
        self.assertIn("browser", names)
        self.assertIn("web_fetch", names)
        self.assertIn("filesystem", names)
        self.assertNotIn("office", names)
        self.assertNotIn("docker", names)

    def test_mixed_keeps_optional_worker_tools_when_available(self) -> None:
        with (
            patch(
                "app.agent.workers.browser_use.browser_use_status",
                lambda: {"available": True, "reason": "mock", "version": "1"},
            ),
            patch(
                "app.agent.workers.computer_use.ufo_status",
                lambda: {"available": True, "reason": "mock", "version": "1"},
            ),
            patch(
                "app.agent.workers.computer_use.cua_status",
                lambda: {"available": False, "reason": "missing", "version": ""},
            ),
            patch(
                "app.agent.workers.openhands.openhands_status",
                lambda: {"available": True, "reason": "mock", "version": "1"},
            ),
            patch(
                "app.agent.workers.open_interpreter.open_interpreter_status",
                lambda: {"available": True, "reason": "mock", "version": "1"},
            ),
        ):
            route = classify_task("Please help.")
        self.assertEqual(route.task_class, "mixed")
        self.assertIn("browser_use", route.offered_tools)
        self.assertIn("ufo", route.offered_tools)
        self.assertIn("openhands", route.offered_tools)
        self.assertIn("open_interpreter", route.offered_tools)
        self.assertNotIn("cua", route.offered_tools)
        self.assertEqual(route.preferred_tools[0], "filesystem")


class TaskRoutingLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t11-"))
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

    async def test_loop_persists_class_and_filters_tools(self) -> None:
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
        async def _ready(*args, **kwargs):
            return True

        manager = SimpleNamespace(
            provider=provider,
            state=SimpleNamespace(loaded=True, profile="fast", thinking_at_process=False),
            record_timings=self._noop,
            load=self._noop,
            ready_for_profile=_ready,
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
        self.assertEqual(task.task_class, "browser")
        self.assertEqual(task.selected_worker, "native")
        names = _names(provider.last_tools)
        self.assertIn("browser", names)
        self.assertIn("web_fetch", names)
        self.assertNotIn("office", names)
        blobs = [
            message.content if isinstance(message.content, str) else str(message.content)
            for message in provider.last_messages
            if message.role == "user"
        ]
        self.assertTrue(any("Task class: Browser automation" in blob for blob in blobs))
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertEqual(stored.task_class, "browser")
        self.assertEqual(stored.selected_worker, "native")
        self.assertIn("browser", stored.plan_json)
        self.assertEqual(stored.status, "completed")


if __name__ == "__main__":
    unittest.main()
