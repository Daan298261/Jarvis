from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings, apply_logging_level
from app.api.settings import router
from app.tools.browser import BrowserTool


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class SettingsCompletenessTests(unittest.TestCase):
    def test_apply_logging_level_changes_root_logger(self) -> None:
        previous = logging.getLogger().level
        try:
            apply_logging_level("WARNING")
            self.assertEqual(logging.getLogger().level, logging.WARNING)
            apply_logging_level("not-a-level")
            self.assertEqual(logging.getLogger().level, logging.INFO)
        finally:
            logging.getLogger().setLevel(previous)

    def test_put_logging_and_browser_timeout(self) -> None:
        stored = {"settings": AppSettings()}

        def load() -> AppSettings:
            return stored["settings"]

        def save(settings: AppSettings) -> None:
            stored["settings"] = settings

        with (
            patch("app.api.settings.load_settings", load),
            patch("app.api.settings.save_settings", save),
        ):
            client = _client()
            bad = client.put("/api/settings", json={"logging_level": "TRACE"})
            self.assertEqual(bad.status_code, 400)
            ok = client.put("/api/settings", json={"logging_level": "debug", "browser_timeout_ms": 15000})
            self.assertEqual(ok.status_code, 200, ok.text)
            body = ok.json()
            self.assertEqual(body["logging_level"], "DEBUG")
            self.assertEqual(body["browser"]["timeout_ms"], 15000)
            self.assertTrue(str(body["log_file"]).endswith("jarvis.log"))
            self.assertEqual(stored["settings"].logging_level, "DEBUG")
            self.assertEqual(stored["settings"].browser.timeout_ms, 15000)
            too_small = client.put("/api/settings", json={"browser_timeout_ms": 50})
            self.assertEqual(too_small.status_code, 400)
        apply_logging_level("INFO")

    def test_browser_tool_reads_timeout_from_settings_context(self) -> None:
        tool = BrowserTool(lambda: {"browser": {"timeout_ms": 12000, "headless": True}})
        self.assertEqual(tool._timeout_ms({}), 12000)
        self.assertEqual(tool._timeout_ms({"timeout_ms": 5000}), 5000)
        self.assertEqual(tool._timeout_ms({"timeout_ms": 10}), 1000)

    def test_settings_page_exposes_logging_timeout_and_thinking(self) -> None:
        source = (ROOT / "frontend" / "src" / "pages" / "Settings.tsx").read_text(encoding="utf-8")
        self.assertIn("logging_level", source)
        self.assertIn("browser_timeout_ms", source)
        self.assertIn("timeout_ms", source)
        self.assertIn("thinking", source.lower())
        self.assertIn("log_file", source)


if __name__ == "__main__":
    unittest.main()
