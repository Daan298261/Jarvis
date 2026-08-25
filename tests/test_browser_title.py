from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings
from app.tools.browser import BrowserTool, reset_browser
from app.tools.registry import REGISTRY


def _playwright_ready() -> str:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        return "Playwright is not installed"
    return ""


class ExampleComTitleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        skip = _playwright_ready()
        if skip:
            self.skipTest(skip)
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t08-title-"))
        self.settings = AppSettings(
            allowed_directories=[str(self.tmp)],
            autonomy="autonomous",
        )
        self.settings.browser.headless = True
        REGISTRY.apply_settings(self.settings)
        self.tool = BrowserTool(lambda: {"allowed_directories": [str(self.tmp)], "browser": {"headless": True}})

    async def asyncTearDown(self) -> None:
        try:
            await reset_browser()
        except Exception:
            pass

    async def test_save_title_writes_example_domain_twice(self) -> None:
        path = self.tmp / "page-title.txt"
        first = await self.tool.execute(
            action="save_title",
            url="https://example.com",
            path=str(path),
            headless=True,
        )
        if not first.success:
            self.skipTest(f"Playwright could not open example.com: {first.error}")
        text = path.read_text(encoding="utf-8")
        self.assertIn("example", text.lower())
        path.write_text("stale\n", encoding="utf-8")
        second = await self.tool.execute(
            action="save_title",
            url="https://example.com",
            path=str(path),
            headless=True,
        )
        self.assertTrue(second.success, second.error)
        again = path.read_text(encoding="utf-8")
        self.assertIn("example", again.lower())
        self.assertNotIn("stale", again.lower())


if __name__ == "__main__":
    unittest.main()
