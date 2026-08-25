from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings
from app.tools.base import RiskLevel
from app.tools.desktop import DesktopTool, _window_matches
from app.tools.registry import REGISTRY


class NotepadDesktopE2ETests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        if sys.platform != "win32":
            self.skipTest("Windows UI automation requires Windows")
        try:
            import pywinauto  # noqa: F401
        except ImportError:
            self.skipTest("pywinauto is not installed")
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t09-"))
        self.settings = AppSettings(allowed_directories=[str(self.tmp)], autonomy="autonomous")
        REGISTRY.apply_settings(self.settings)
        self.tool = DesktopTool(lambda: {"allowed_directories": [str(self.tmp)]})

    async def test_notepad_write_is_verified_on_disk(self) -> None:
        token = f"JARVIS-DESKTOP-E2E-{int(time.time())}"
        path = self.tmp / "notepad-e2e.txt"
        result = await self.tool.execute(action="write", path=str(path), text=token)
        self.assertTrue(result.success, result.error)
        self.assertTrue(path.exists(), result.output)
        text = path.read_text(encoding="utf-8", errors="replace")
        self.assertIn(token, text)
        self.assertIn("Notepad", result.output)

    def test_empty_title_does_not_match_every_window(self) -> None:
        self.assertFalse(_window_matches("Notepad - untitled", ""))
        self.assertFalse(_window_matches("Notepad - untitled", " "))
        self.assertFalse(_window_matches("Notepad - untitled", "a"))
        self.assertTrue(_window_matches("Notepad - untitled", "Notepad"))
        self.assertEqual(DesktopTool.risk, RiskLevel.MEDIUM)


if __name__ == "__main__":
    unittest.main()
