from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.routing import NATIVE_WORKER, get_workers, list_workers, resolve_worker
from app.api.tools import router
from app.config import AppSettings


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class WorkerToggleTests(unittest.TestCase):
    def test_disabled_worker_is_unavailable_and_falls_back(self) -> None:
        settings = AppSettings(disabled_workers=["docker"])
        with patch("app.config.load_settings", return_value=settings):
            workers = get_workers()
            self.assertFalse(workers["docker"].available)
            self.assertIn("Disabled on the Tools page", workers["docker"].reason)
            self.assertEqual(resolve_worker("docker").name, NATIVE_WORKER)
            row = next(item for item in list_workers() if item["name"] == "docker")
            self.assertFalse(row["enabled"])
            self.assertTrue(row["can_toggle"])
            native = next(item for item in list_workers() if item["name"] == NATIVE_WORKER)
            self.assertTrue(native["enabled"])
            self.assertFalse(native["can_toggle"])
            self.assertEqual(list_workers()[0]["name"], NATIVE_WORKER)

    def test_disable_and_enable_worker_via_api(self) -> None:
        stored = {"settings": AppSettings(disabled_workers=[])}

        def load() -> AppSettings:
            return stored["settings"]

        def save(settings: AppSettings) -> None:
            stored["settings"] = settings

        with (
            patch("app.api.tools.load_settings", load),
            patch("app.api.tools.save_settings", save),
            patch("app.config.load_settings", load),
        ):
            client = _client()
            disabled = client.post("/api/tools/workers/docker/disable")
            self.assertEqual(disabled.status_code, 200, disabled.text)
            body = disabled.json()
            self.assertEqual(body["name"], "docker")
            self.assertFalse(body["enabled"])
            self.assertFalse(body["available"])
            self.assertIn("docker", stored["settings"].disabled_workers)

            enabled = client.post("/api/tools/workers/docker/enable")
            self.assertEqual(enabled.status_code, 200, enabled.text)
            self.assertTrue(enabled.json()["enabled"])
            self.assertNotIn("docker", stored["settings"].disabled_workers)

            native = client.post("/api/tools/workers/native/disable")
            self.assertEqual(native.status_code, 400)
            missing = client.post("/api/tools/workers/nope/disable")
            self.assertEqual(missing.status_code, 404)

    def test_tools_page_has_worker_toggles(self) -> None:
        source = (ROOT / "frontend" / "src" / "pages" / "Tools.tsx").read_text(encoding="utf-8")
        self.assertIn("/api/tools/workers/", source)
        self.assertIn("can_toggle", source)
        self.assertIn("Disabled", source)
        self.assertIn("unavailable", source)


if __name__ == "__main__":
    unittest.main()
