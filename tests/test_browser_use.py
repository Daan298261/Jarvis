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
from app.agent.workers.browser_use import browser_use_status, run_browser_task
from app.config import AppSettings
from app.db.models import Base, Task
from app.providers.base import ChatResult
from app.tools.browser_use import BrowserUseTool
from app.tools.registry import REGISTRY

UNAVAILABLE = {
    "available": False,
    "reason": "browser-use package is not installed; using Playwright",
    "version": "",
}
AVAILABLE = {"available": True, "reason": "browser-use package is installed (mock)", "version": "mock"}
UNKNOWN_SITE = (
    "Open a browser, visit https://unfamiliar-intranet.test/admin, "
    "and click through the unknown dashboard to export a report to {path}."
)
EXAMPLE_SITE = (
    "Open a browser, visit https://example.com, read the page title, and save that title to {path}."
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


class BrowserUseAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_status_unavailable_without_package(self) -> None:
        with patch.dict(sys.modules, {"browser_use": None}):
            status = browser_use_status()
        self.assertFalse(status["available"])
        self.assertIn("Playwright", status["reason"])

    async def test_run_degrades_when_missing(self) -> None:
        with patch("app.agent.workers.browser_use.browser_use_status", lambda: UNAVAILABLE):
            result = await run_browser_task("Click through the unknown dashboard", url="https://unfamiliar-intranet.test")
        self.assertFalse(result["success"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["worker"], "native")
        self.assertIn("Playwright", result["fallback"])
        self.assertIn("orchestrator", result["note"].lower())

    async def test_tool_status_and_run_when_missing(self) -> None:
        tool = BrowserUseTool()
        with patch("app.agent.workers.browser_use.browser_use_status", lambda: UNAVAILABLE):
            status = await tool.execute(action="status")
            run = await tool.execute(action="run", goal="discover the admin UI", url="https://unfamiliar-intranet.test")
        self.assertTrue(status.success)
        self.assertIn("Playwright", status.output)
        self.assertFalse(run.success)
        self.assertIn("Playwright", run.output)
        self.assertIn("orchestrator", run.output.lower())

    async def test_tool_run_when_available_returns_worker_output(self) -> None:
        async def fake_run(goal, url=None, max_steps=8):
            return {
                "success": True,
                "degraded": False,
                "worker": "browser_use",
                "output": f"Found export button on {url} for {goal}",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator. Write and verify any requested files with native tools.",
            }

        tool = BrowserUseTool()
        with (
            patch("app.agent.workers.browser_use.browser_use_status", lambda: AVAILABLE),
            patch("app.agent.workers.browser_use.run_browser_task", fake_run),
        ):
            result = await tool.execute(action="run", goal="export a report", url="https://unfamiliar-intranet.test/admin")
        self.assertTrue(result.success)
        self.assertIn("Found export button", result.output)
        self.assertIn("orchestrator", result.output.lower())
        self.assertEqual(result.data["worker"], "browser_use")

    def test_unknown_site_selects_worker_when_available(self) -> None:
        with patch("app.agent.workers.browser_use.browser_use_status", lambda: AVAILABLE):
            route = classify_task(UNKNOWN_SITE.format(path="report.txt"))
            workers = list_workers()
            resolved = resolve_worker("browser_use")
        self.assertEqual(route.task_class, "browser")
        self.assertEqual(route.preferred_worker, "browser_use")
        self.assertEqual(route.worker, "browser_use")
        self.assertFalse(route.degraded)
        self.assertIn("browser_use", route.offered_tools)
        self.assertIn("browser", route.offered_tools)
        self.assertIn("Unknown website", route.prompt_hint())
        self.assertIn("orchestrator", route.prompt_hint().lower())
        self.assertEqual(resolved.name, "browser_use")
        row = [item for item in workers if item["name"] == "browser_use"][0]
        self.assertTrue(row["available"])

    def test_known_site_stays_native_even_when_worker_available(self) -> None:
        with patch("app.agent.workers.browser_use.browser_use_status", lambda: AVAILABLE):
            route = classify_task(EXAMPLE_SITE.format(path="page-title.txt"))
        self.assertEqual(route.worker, "native")
        self.assertFalse(route.degraded)
        self.assertNotIn("browser_use", route.offered_tools)
        self.assertIn("Known website workflow", route.prompt_hint())

    def test_catalog_includes_browser_use_tool(self) -> None:
        names = {tool.name for tool in REGISTRY.tools.values()}
        self.assertIn("browser_use", names)

    def test_recovery_falls_back_to_playwright(self) -> None:
        with patch("app.agent.workers.browser_use.browser_use_status", lambda: UNAVAILABLE):
            self.assertIn("browser", alternate_tools("browser_use"))
            self.assertIn("web_fetch", alternate_tools("browser_use"))
            self.assertNotIn("browser_use", alternate_tools("browser"))
        with patch("app.agent.workers.browser_use.browser_use_status", lambda: AVAILABLE):
            self.assertIn("browser_use", alternate_tools("browser"))
            self.assertIn("browser", alternate_tools("browser_use"))


class BrowserUseLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t14-"))
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

    async def test_loop_uses_worker_then_native_write(self) -> None:
        target = self.tmp / "export-report.txt"

        async def fake_run(goal, url=None, max_steps=8):
            return {
                "success": True,
                "degraded": False,
                "worker": "browser_use",
                "output": "Discovered the export control and copied REPORT-OK",
                "error": "",
                "fallback": "",
                "note": "Jarvis remains the orchestrator. Write and verify any requested files with native tools.",
            }

        provider = ScriptedProvider(
            [
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c1",
                            "browser_use",
                            {
                                "action": "run",
                                "goal": "export a report from the unknown dashboard",
                                "url": "https://unfamiliar-intranet.test/admin",
                            },
                        )
                    ]
                ),
                ChatResult(
                    tool_calls=[
                        _tool_call(
                            "c2",
                            "filesystem",
                            {"action": "write", "path": str(target), "content": "REPORT-OK"},
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
        prompt = UNKNOWN_SITE.format(path=target)
        with (
            patch("app.agent.loop.SessionLocal", self.sessions),
            patch("app.events.SessionLocal", self.sessions),
            patch("app.agent.resume.SessionLocal", self.sessions),
            patch("app.agent.loop.MANAGER", manager),
            patch("app.agent.loop.load_settings", lambda: self.settings),
            patch("app.agent.workers.browser_use.browser_use_status", lambda: AVAILABLE),
            patch("app.agent.workers.browser_use.run_browser_task", fake_run),
        ):
            task = await runtime.create_task(prompt, autonomy="autonomous", profile="fast")
            await runtime._tasks[task.id]
        self.assertEqual(task.task_class, "browser")
        self.assertEqual(task.selected_worker, "browser_use")
        names = _names(provider.last_tools)
        self.assertIn("browser_use", names)
        self.assertIn("browser", names)
        self.assertNotIn("office", names)
        blobs = [
            message.content if isinstance(message.content, str) else str(message.content)
            for message in provider.last_messages
            if message.role == "user"
        ]
        self.assertTrue(any("Unknown website" in blob and "orchestrator" in blob.lower() for blob in blobs))
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8").strip(), "REPORT-OK")
        async with self.sessions() as session:
            stored = await session.get(Task, task.id)
        assert stored is not None
        self.assertEqual(stored.selected_worker, "browser_use")
        self.assertEqual(stored.status, "completed")


if __name__ == "__main__":
    unittest.main()
