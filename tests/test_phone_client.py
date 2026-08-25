from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.tasks import TaskCreate, cancel_task, continue_task, create_task, get_task, list_tasks
from app.phone import PHONE_PATH, TASK_API, lan_ipv4_addresses, phone_status, phone_urls


class PhoneClientTests(unittest.TestCase):
    def test_task_api_matches_live_routes(self) -> None:
        self.assertEqual(TASK_API["create"]["method"], "POST")
        self.assertEqual(TASK_API["create"]["path"], "/api/tasks")
        self.assertEqual(TASK_API["list"]["path"], "/api/tasks")
        self.assertEqual(TASK_API["get"]["path"], "/api/tasks/{id}")
        self.assertEqual(TASK_API["continue"]["path"], "/api/tasks/{id}/continue")
        self.assertEqual(TASK_API["cancel"]["path"], "/api/tasks/{id}/cancel")
        self.assertIn("prompt", TaskCreate.model_fields)
        self.assertIn("autonomy", TaskCreate.model_fields)
        self.assertIn("execution_mode", TaskCreate.model_fields)
        self.assertTrue(inspect.iscoroutinefunction(create_task))
        self.assertTrue(inspect.iscoroutinefunction(list_tasks))
        self.assertTrue(inspect.iscoroutinefunction(get_task))
        self.assertTrue(inspect.iscoroutinefunction(continue_task))
        self.assertTrue(inspect.iscoroutinefunction(cancel_task))

    def test_phone_path_and_localhost_url(self) -> None:
        self.assertEqual(PHONE_PATH, "/phone")
        urls = phone_urls(4780)
        self.assertIn("http://127.0.0.1:4780/phone", urls)

    def test_lan_urls_only_when_lan_and_token(self) -> None:
        with patch("app.phone.usable_auth_token", return_value=""), patch("app.phone.load_settings") as settings:
            settings.return_value.lan_access = True
            settings.return_value.bind_port = 4780
            status = phone_status()
        self.assertFalse(status["reachable_from_lan"])
        self.assertEqual(status["urls"], ["http://127.0.0.1:4780/phone"])
        self.assertFalse(any("192." in url or "10." in url for url in status["urls"]))

    def test_loopback_ips_are_not_advertised_as_lan(self) -> None:
        ips = lan_ipv4_addresses()
        for ip in ips:
            self.assertFalse(ip.startswith("127."))
            self.assertFalse(ip.startswith("169.254."))

    def test_phone_ui_calls_task_api(self) -> None:
        source = (ROOT / "frontend" / "src" / "pages" / "Phone.tsx").read_text(encoding="utf-8")
        self.assertIn('"/api/tasks"', source)
        self.assertIn("`/api/tasks/${activeId}`", source)
        self.assertIn("/continue", source)
        self.assertIn("/cancel", source)
        self.assertIn("X-Jarvis-Token", source)

    def test_spa_serves_phone_as_index(self) -> None:
        source = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"phone"', source)
        self.assertIn("index.html", source)

    def test_lan_urls_when_token_and_bind_ready(self) -> None:
        fake = type("S", (), {"lan_access": True, "bind_port": 4780})()
        with (
            patch("app.phone.load_settings", return_value=fake),
            patch("app.phone.usable_auth_token", return_value="jarvis-lan-token-1"),
            patch("app.phone.uvicorn_bind_host", return_value="0.0.0.0"),
            patch("app.phone.lan_ipv4_addresses", return_value=["192.168.1.20"]),
        ):
            urls = phone_urls()
        self.assertIn("http://127.0.0.1:4780/phone", urls)
        self.assertIn("http://192.168.1.20:4780/phone", urls)

    def test_android_webview_injects_same_token(self) -> None:
        kotlin = (ROOT / "clients" / "android" / "app" / "src" / "main" / "java" / "local" / "jarvis" / "phone" / "MainActivity.kt").read_text(encoding="utf-8")
        self.assertIn("jarvis_auth_token", kotlin)
        self.assertIn("WebView", kotlin)
        self.assertIn("/phone", kotlin)

    def test_android_api_hits_task_routes(self) -> None:
        kotlin = (ROOT / "clients" / "android" / "JarvisApi.kt").read_text(encoding="utf-8")
        self.assertIn("POST", kotlin)
        self.assertIn("/api/tasks", kotlin)
        self.assertIn("/continue", kotlin)
        self.assertIn("/cancel", kotlin)
        self.assertIn("X-Jarvis-Token", kotlin)

    def test_python_phone_client_uses_task_api_and_token(self) -> None:
        sys.path.insert(0, str(ROOT / "clients" / "phone"))
        import httpx
        from jarvis_client import ENDPOINTS, JarvisPhoneClient

        self.assertEqual(ENDPOINTS["create"], "POST /api/tasks")
        seen: list[tuple[str, str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, str(request.url.path), request.headers.get("x-jarvis-token", "")))
            if request.url.path == "/api/health":
                return httpx.Response(200, json={"ok": True})
            if request.method == "POST" and request.url.path == "/api/tasks":
                return httpx.Response(200, json={"id": "t1", "status": "queued", "prompt": "hi"})
            if request.url.path == "/api/tasks/t1":
                return httpx.Response(200, json={"id": "t1", "status": "running"})
            if request.url.path.endswith("/continue"):
                return httpx.Response(200, json={"id": "t1", "status": "running"})
            if request.url.path.endswith("/cancel"):
                return httpx.Response(200, json={"id": "t1", "status": "cancelled"})
            if request.url.path == "/api/tasks":
                return httpx.Response(200, json=[{"id": "t1"}])
            return httpx.Response(404, json={"detail": "missing"})

        transport = httpx.MockTransport(handler)
        http = httpx.Client(base_url="http://192.168.1.20:4780/", transport=transport)
        with JarvisPhoneClient("http://192.168.1.20:4780", token="jarvis-lan-token-1", client=http) as client:
            self.assertTrue(client.health()["ok"])
            created = client.create_task("hi")
            self.assertEqual(created["id"], "t1")
            self.assertEqual(client.get_task("t1")["id"], "t1")
            client.continue_task("t1", prompt="Continue this.")
            client.cancel_task("t1")
            self.assertEqual(client.list_tasks()[0]["id"], "t1")
        self.assertTrue(all(token == "jarvis-lan-token-1" for _, _, token in seen))
        self.assertIn(("POST", "/api/tasks", "jarvis-lan-token-1"), seen)

    def test_phone_info_http_and_task_api_via_testclient(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.phone import router as phone_router

        mini = FastAPI()
        mini.include_router(phone_router)

        @mini.post("/api/tasks")
        def create():
            return {"id": "t1", "status": "queued", "prompt": "hi"}

        @mini.get("/api/tasks")
        def listing():
            return [{"id": "t1"}]

        @mini.get("/api/tasks/{tid}")
        def get(tid: str):
            return {"id": tid, "status": "running"}

        @mini.post("/api/tasks/{tid}/continue")
        def cont(tid: str):
            return {"id": tid, "status": "running"}

        @mini.post("/api/tasks/{tid}/cancel")
        def canc(tid: str):
            return {"id": tid, "status": "cancelled"}

        http = TestClient(mini)
        payload = http.get("/api/phone").json()
        self.assertEqual(payload["client"], "phone")
        self.assertEqual(payload["task_api"]["create"]["path"], "/api/tasks")
        self.assertTrue(payload["urls"][0].endswith("/phone"))

        sys.path.insert(0, str(ROOT / "clients" / "phone"))
        from jarvis_client import JarvisPhoneClient

        with JarvisPhoneClient("http://testserver", token="jarvis-lan-token-1", client=http) as phone:
            self.assertEqual(phone.create_task("hi")["id"], "t1")
            self.assertEqual(phone.get_task("t1")["id"], "t1")
            self.assertEqual(phone.continue_task("t1", prompt="Continue this.")["id"], "t1")
            self.assertEqual(phone.cancel_task("t1")["status"], "cancelled")
            self.assertEqual(phone.list_tasks()[0]["id"], "t1")


class PhoneApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_phone_info_endpoint(self) -> None:
        from app.api.phone import phone_info

        payload = await phone_info()
        self.assertEqual(payload["client"], "phone")
        self.assertEqual(payload["auth_header"], "X-Jarvis-Token")
        self.assertEqual(payload["task_api"]["create"]["path"], "/api/tasks")
        self.assertTrue(payload["urls"][0].endswith("/phone"))


if __name__ == "__main__":
    unittest.main()
