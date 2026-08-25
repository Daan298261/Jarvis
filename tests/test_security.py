from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings, save_settings
from app.security import (
    MIN_TOKEN_LENGTH,
    apply_listen_policy,
    extract_request_token,
    is_loopback_host,
    lan_api_denied,
    llama_bind_host,
    token_matches,
    usable_auth_token,
    uvicorn_bind_host,
)

TOKEN = "a" * MIN_TOKEN_LENGTH
SHORT = "short-token"


def _mini_app(lan: bool) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        denied = lan_api_denied(
            request.client.host if request.client else "",
            request.headers.get("authorization"),
            request.headers.get("x-jarvis-token"),
            lan,
            usable_auth_token(),
            None,
            allow_query_token=False,
        )
        if denied:
            status, detail = denied
            return JSONResponse({"detail": detail}, status_code=status)
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app


class LoopbackTests(unittest.TestCase):
    def test_loopback_variants(self) -> None:
        for host in ("127.0.0.1", "localhost", "::1", "testclient", "127.9.9.9", "::ffff:127.0.0.1"):
            self.assertTrue(is_loopback_host(host), host)
        self.assertFalse(is_loopback_host("192.168.1.20"))
        self.assertFalse(is_loopback_host("10.0.0.8"))
        self.assertFalse(is_loopback_host("0.0.0.0"))


class BindHostTests(unittest.TestCase):
    def test_default_is_localhost(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_AUTH_TOKEN", None)
            os.environ.pop("JARVIS_BIND_HOST", None)
            self.assertEqual(uvicorn_bind_host(False), "127.0.0.1")
            self.assertEqual(uvicorn_bind_host(True), "127.0.0.1")

    def test_lan_without_token_stays_localhost(self) -> None:
        with patch.dict(os.environ, {"JARVIS_AUTH_TOKEN": "", "JARVIS_BIND_HOST": "0.0.0.0"}, clear=False):
            self.assertEqual(uvicorn_bind_host(True, ""), "127.0.0.1")

    def test_short_token_does_not_open_lan(self) -> None:
        with patch.dict(os.environ, {"JARVIS_AUTH_TOKEN": SHORT}, clear=False):
            os.environ.pop("JARVIS_BIND_HOST", None)
            self.assertEqual(usable_auth_token(), "")
            self.assertEqual(uvicorn_bind_host(True), "127.0.0.1")

    def test_lan_with_token_binds_all_interfaces(self) -> None:
        with patch.dict(os.environ, {"JARVIS_AUTH_TOKEN": TOKEN}, clear=False):
            os.environ.pop("JARVIS_BIND_HOST", None)
            self.assertEqual(uvicorn_bind_host(True), "0.0.0.0")
            self.assertEqual(uvicorn_bind_host(False), "127.0.0.1")

    def test_bind_host_override_ignored_without_lan_token(self) -> None:
        with patch.dict(os.environ, {"JARVIS_BIND_HOST": "192.168.1.5", "JARVIS_AUTH_TOKEN": TOKEN}):
            self.assertEqual(uvicorn_bind_host(False), "127.0.0.1")
        with patch.dict(os.environ, {"JARVIS_BIND_HOST": "192.168.1.5", "JARVIS_AUTH_TOKEN": TOKEN}):
            self.assertEqual(uvicorn_bind_host(True), "192.168.1.5")

    def test_llama_stays_loopback(self) -> None:
        self.assertEqual(llama_bind_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(llama_bind_host("192.168.1.9"), "127.0.0.1")
        self.assertEqual(llama_bind_host("127.0.0.1"), "127.0.0.1")


class ListenPolicyTests(unittest.TestCase):
    def test_file_token_is_dropped(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_AUTH_TOKEN", None)
            for key in (
                "JARVIS_INFERENCE_BACKEND",
                "JARVIS_INFERENCE_HOST",
                "JARVIS_INFERENCE_PORT",
                "JARVIS_INFERENCE_BASE_URL",
            ):
                os.environ.pop(key, None)
            out = apply_listen_policy({"lan_access": True, "auth_token": "from-file", "inference": {"host": "10.0.0.2"}})
            self.assertNotIn("from-file", json.dumps(out))
            self.assertEqual(out["bind_host"], "127.0.0.1")
            self.assertFalse(out["auth_required"])
            self.assertEqual(out["inference"]["host"], "127.0.0.1")

    def test_lan_and_env_token_enables_auth(self) -> None:
        with patch.dict(os.environ, {"JARVIS_AUTH_TOKEN": TOKEN}):
            os.environ.pop("JARVIS_BIND_HOST", None)
            out = apply_listen_policy({"lan_access": True, "auth_token": "file-secret"})
            self.assertTrue(out["auth_required"])
            self.assertEqual(out["bind_host"], "0.0.0.0")
            self.assertEqual(out["auth_token"], TOKEN)

    def test_save_settings_never_writes_auth_token(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-t22-"))
        settings = AppSettings(lan_access=True, auth_token="should-not-land-on-disk")
        with patch("app.config.settings_path", lambda: tmp / "settings.json"):
            with patch("app.backup.snapshot", lambda **_kwargs: None):
                save_settings(settings)
        dumped = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
        self.assertNotIn("auth_token", dumped)


class LanApiDeniedTests(unittest.TestCase):
    def test_loopback_skips_auth(self) -> None:
        self.assertIsNone(lan_api_denied("127.0.0.1", None, None, False, TOKEN))
        self.assertIsNone(lan_api_denied("::1", None, None, True, TOKEN))

    def test_lan_off_blocks_remote(self) -> None:
        denied = lan_api_denied("192.168.0.4", None, None, False, TOKEN)
        self.assertEqual(denied[0], 403)

    def test_lan_on_requires_header_or_bearer(self) -> None:
        remote = "10.0.0.9"
        self.assertEqual(lan_api_denied(remote, None, None, True, TOKEN)[0], 401)
        self.assertEqual(lan_api_denied(remote, None, "wrong-token-value", True, TOKEN)[0], 401)
        self.assertIsNone(lan_api_denied(remote, None, TOKEN, True, TOKEN))
        self.assertIsNone(lan_api_denied(remote, f"Bearer {TOKEN}", None, True, TOKEN))

    def test_http_ignores_query_token(self) -> None:
        denied = lan_api_denied(
            "10.0.0.9",
            None,
            None,
            True,
            TOKEN,
            query_token=TOKEN,
            allow_query_token=False,
        )
        self.assertEqual(denied[0], 401)

    def test_websocket_may_use_query_token(self) -> None:
        self.assertIsNone(
            lan_api_denied(
                "10.0.0.9",
                None,
                None,
                True,
                TOKEN,
                query_token=TOKEN,
                allow_query_token=True,
            )
        )

    def test_extract_prefers_bearer_then_header(self) -> None:
        self.assertEqual(extract_request_token("Bearer abc", "hdr", "q", allow_query=True), "abc")
        self.assertEqual(extract_request_token(None, "hdr", "q", allow_query=True), "hdr")
        self.assertEqual(extract_request_token(None, None, "q", allow_query=False), "")
        self.assertEqual(extract_request_token(None, None, "q", allow_query=True), "q")

    def test_token_match_is_exact(self) -> None:
        self.assertTrue(token_matches(TOKEN, TOKEN))
        self.assertFalse(token_matches(TOKEN + "x", TOKEN))
        self.assertFalse(token_matches("", TOKEN))
        self.assertFalse(token_matches(TOKEN, ""))


class HttpMiddlewareTests(unittest.TestCase):
    def test_loopback_health_without_token(self) -> None:
        with patch.dict(os.environ, {"JARVIS_AUTH_TOKEN": TOKEN}):
            client = TestClient(_mini_app(lan=True))
            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)

    def test_remote_health_requires_header_not_query(self) -> None:
        with patch.dict(os.environ, {"JARVIS_AUTH_TOKEN": TOKEN}):
            client = TestClient(_mini_app(lan=True), client=("192.168.1.50", 4321))
            self.assertEqual(client.get("/api/health").status_code, 401)
            self.assertEqual(client.get(f"/api/health?token={TOKEN}").status_code, 401)
            ok = client.get("/api/health", headers={"X-Jarvis-Token": TOKEN})
            self.assertEqual(ok.status_code, 200)
            bearer = client.get("/api/health", headers={"Authorization": f"Bearer {TOKEN}"})
            self.assertEqual(bearer.status_code, 200)

    def test_remote_blocked_when_lan_off(self) -> None:
        with patch.dict(os.environ, {"JARVIS_AUTH_TOKEN": TOKEN}):
            client = TestClient(_mini_app(lan=False), client=("192.168.1.50", 4321))
            self.assertEqual(client.get("/api/health").status_code, 403)


if __name__ == "__main__":
    unittest.main()
