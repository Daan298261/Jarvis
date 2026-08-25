from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings, load_settings, save_settings
from app.security import (
    MIN_TOKEN_LENGTH,
    apply_listen_policy,
    lan_api_denied,
    token_matches,
    uvicorn_bind_host,
)

TOKEN = "jarvis-lan-token-1"


class LanAuthPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._token = os.environ.pop("JARVIS_AUTH_TOKEN", None)
        self._bind = os.environ.pop("JARVIS_BIND_HOST", None)

    def tearDown(self) -> None:
        os.environ.pop("JARVIS_AUTH_TOKEN", None)
        os.environ.pop("JARVIS_BIND_HOST", None)
        if self._token is not None:
            os.environ["JARVIS_AUTH_TOKEN"] = self._token
        if self._bind is not None:
            os.environ["JARVIS_BIND_HOST"] = self._bind

    def test_default_json_is_localhost(self) -> None:
        raw = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))
        self.assertEqual(raw.get("bind_host"), "127.0.0.1")
        self.assertFalse(raw.get("lan_access"))
        self.assertEqual(raw.get("inference", {}).get("host"), "127.0.0.1")

    def test_bind_stays_localhost_without_token(self) -> None:
        self.assertEqual(uvicorn_bind_host(True, ""), "127.0.0.1")
        self.assertEqual(uvicorn_bind_host(False, TOKEN), "127.0.0.1")
        self.assertEqual(uvicorn_bind_host(True, "short"), "127.0.0.1")
        os.environ["JARVIS_AUTH_TOKEN"] = "tooshort"
        self.assertEqual(uvicorn_bind_host(True), "127.0.0.1")

    def test_bind_opens_lan_only_with_token(self) -> None:
        os.environ["JARVIS_AUTH_TOKEN"] = TOKEN
        self.assertEqual(uvicorn_bind_host(True), "0.0.0.0")
        os.environ["JARVIS_BIND_HOST"] = "192.168.1.20"
        self.assertEqual(uvicorn_bind_host(True), "192.168.1.20")

    def test_file_token_is_ignored(self) -> None:
        out = apply_listen_policy({"lan_access": True, "auth_token": "from-file-secret!!", "bind_host": "0.0.0.0"})
        self.assertEqual(out["bind_host"], "127.0.0.1")
        self.assertEqual(out["auth_token"], "")
        os.environ["JARVIS_AUTH_TOKEN"] = TOKEN
        out = apply_listen_policy({"lan_access": True, "auth_token": "from-file-secret!!"})
        self.assertEqual(out["auth_token"], TOKEN)
        self.assertEqual(out["bind_host"], "0.0.0.0")

    def test_inference_host_cannot_leave_loopback(self) -> None:
        for key in ("JARVIS_INFERENCE_BACKEND", "JARVIS_INFERENCE_HOST", "JARVIS_INFERENCE_PORT", "JARVIS_INFERENCE_BASE_URL"):
            os.environ.pop(key, None)
        out = apply_listen_policy({"inference": {"host": "0.0.0.0"}})
        self.assertEqual(out["inference"]["host"], "127.0.0.1")

    def test_remote_inference_host_is_kept(self) -> None:
        for key in ("JARVIS_INFERENCE_BACKEND", "JARVIS_INFERENCE_HOST", "JARVIS_INFERENCE_PORT", "JARVIS_INFERENCE_BASE_URL"):
            os.environ.pop(key, None)
        out = apply_listen_policy({"inference": {"backend": "openai-compat", "host": "192.168.1.50", "port": 8080}})
        self.assertEqual(out["inference"]["host"], "192.168.1.50")
        self.assertEqual(out["inference"]["backend"], "openai-compat")

    def test_loopback_never_requires_token(self) -> None:
        self.assertIsNone(lan_api_denied("127.0.0.1", None, None, True, TOKEN))
        self.assertIsNone(lan_api_denied("testclient", None, None, True, TOKEN))
        self.assertIsNone(lan_api_denied("::1", None, None, False, ""))

    def test_nonlocal_denied_when_lan_off(self) -> None:
        denied = lan_api_denied("192.168.1.50", None, None, False, TOKEN)
        self.assertEqual(denied[0], 403)

    def test_nonlocal_denied_without_token_header(self) -> None:
        denied = lan_api_denied("192.168.1.50", None, None, True, TOKEN)
        self.assertEqual(denied[0], 401)
        denied = lan_api_denied("192.168.1.50", None, None, True, "")
        self.assertEqual(denied[0], 403)
        denied = lan_api_denied("192.168.1.50", None, None, True, "short")
        self.assertEqual(denied[0], 403)

    def test_nonlocal_allowed_with_bearer_or_header(self) -> None:
        self.assertIsNone(lan_api_denied("192.168.1.50", f"Bearer {TOKEN}", None, True, TOKEN))
        self.assertIsNone(lan_api_denied("192.168.1.50", None, TOKEN, True, TOKEN))
        self.assertIsNone(
            lan_api_denied("192.168.1.50", None, None, True, TOKEN, TOKEN, allow_query_token=True)
        )
        self.assertEqual(
            lan_api_denied("192.168.1.50", None, None, True, TOKEN, TOKEN, allow_query_token=False)[0],
            401,
        )
        self.assertEqual(lan_api_denied("192.168.1.50", "Bearer wrong-token-16", None, True, TOKEN)[0], 401)

    def test_token_compare_is_constant_time_and_rejects_mismatch(self) -> None:
        self.assertTrue(token_matches("abc", "abc"))
        self.assertFalse(token_matches("abc", "abd"))
        self.assertFalse(token_matches("", "abc"))
        self.assertFalse(token_matches("abc", ""))

    def test_start_script_uses_policy_helper(self) -> None:
        script = (ROOT / "start-jarvis.ps1").read_text(encoding="utf-8")
        self.assertIn("uvicorn_bind_host_from_files", script)
        self.assertIn("127.0.0.1:4780/api/health", script)


class SettingsPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t22-"))
        self.default = self.tmp / "default.json"
        self.settings = self.tmp / "settings.json"
        self.default.write_text(
            json.dumps(
                {
                    "bind_host": "127.0.0.1",
                    "lan_access": False,
                    "auth_required": False,
                    "inference": {"host": "0.0.0.0"},
                }
            ),
            encoding="utf-8",
        )
        self._token = os.environ.pop("JARVIS_AUTH_TOKEN", None)
        self.patches = [
            patch("app.config.default_config_path", lambda: self.default),
            patch("app.config.settings_path", lambda: self.settings),
            patch("app.backup.snapshot", lambda **_kw: None),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        os.environ.pop("JARVIS_AUTH_TOKEN", None)
        if self._token is not None:
            os.environ["JARVIS_AUTH_TOKEN"] = self._token

    def test_load_forces_localhost_and_ignores_file_token(self) -> None:
        self.settings.write_text(
            json.dumps({"auth_token": "leaked", "lan_access": True, "bind_host": "0.0.0.0"}),
            encoding="utf-8",
        )
        loaded = load_settings()
        self.assertEqual(loaded.bind_host, "127.0.0.1")
        self.assertEqual(loaded.auth_token, "")
        self.assertEqual(loaded.inference.host, "127.0.0.1")

    def test_save_never_writes_auth_token(self) -> None:
        os.environ["JARVIS_AUTH_TOKEN"] = TOKEN
        save_settings(
            AppSettings(lan_access=True, auth_required=True, auth_token=TOKEN, bind_host="0.0.0.0")
        )
        dumped = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertNotIn("auth_token", dumped)

    async def test_enable_lan_without_token_is_400(self) -> None:
        from fastapi import HTTPException

        from app.api.settings import SettingsUpdate, update_settings

        with self.assertRaises(HTTPException) as raised:
            await update_settings(SettingsUpdate(lan_access=True))
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("JARVIS_AUTH_TOKEN", str(raised.exception.detail))

    async def test_enable_lan_with_token_binds_all_interfaces(self) -> None:
        os.environ["JARVIS_AUTH_TOKEN"] = TOKEN
        from app.api.settings import SettingsUpdate, update_settings

        with patch("app.api.settings.REGISTRY") as registry:
            registry.apply_settings = lambda _s: None
            payload = await update_settings(SettingsUpdate(lan_access=True))
        self.assertTrue(payload["lan_access"])
        self.assertEqual(payload["bind_host"], "0.0.0.0")
        self.assertTrue(payload["auth_token_configured"])
        self.assertNotIn("auth_token", payload)
        dumped = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertTrue(dumped["lan_access"])
        self.assertEqual(dumped["bind_host"], "0.0.0.0")
        self.assertNotIn("auth_token", dumped)

    async def test_enable_lan_with_short_token_is_400(self) -> None:
        os.environ["JARVIS_AUTH_TOKEN"] = "short"
        from fastapi import HTTPException

        from app.api.settings import SettingsUpdate, update_settings

        with self.assertRaises(HTTPException) as raised:
            await update_settings(SettingsUpdate(lan_access=True))
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn(str(MIN_TOKEN_LENGTH), str(raised.exception.detail))

    async def test_bind_host_payload_cannot_open_lan_without_token(self) -> None:
        from fastapi import HTTPException

        from app.api.settings import SettingsUpdate, update_settings

        with self.assertRaises(HTTPException) as raised:
            await update_settings(SettingsUpdate(bind_host="0.0.0.0"))
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
