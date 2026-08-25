from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings, save_settings
from app.inference.endpoint import (
    inference_base_url,
    is_remote_inference,
    normalize_base_url,
)
from app.inference.manager import InferenceManager
from app.providers.openai_compat import OpenAICompatProvider
from app.security import apply_listen_policy, llama_bind_host

INFERENCE_ENV = (
    "JARVIS_INFERENCE_BACKEND",
    "JARVIS_INFERENCE_HOST",
    "JARVIS_INFERENCE_PORT",
    "JARVIS_INFERENCE_BASE_URL",
    "JARVIS_INFERENCE_MODEL",
    "JARVIS_INFERENCE_API_KEY",
)


class InferenceEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {key: os.environ.pop(key, None) for key in INFERENCE_ENV}

    def tearDown(self) -> None:
        for key in INFERENCE_ENV:
            os.environ.pop(key, None)
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value


class EndpointPolicyTests(InferenceEnvTest):
    def test_default_settings_are_local(self) -> None:
        settings = AppSettings()
        self.assertFalse(is_remote_inference(settings))
        self.assertEqual(settings.inference.host, "127.0.0.1")
        self.assertEqual(settings.inference.port, 8088)
        self.assertEqual(inference_base_url(settings), "http://127.0.0.1:8088/v1")
        self.assertEqual(llama_bind_host("192.168.1.9"), "127.0.0.1")

    def test_bind_all_interfaces_still_loopback_for_local(self) -> None:
        out = apply_listen_policy({"inference": {"backend": "llama.cpp", "host": "0.0.0.0"}})
        self.assertEqual(out["inference"]["host"], "127.0.0.1")
        self.assertEqual(out["inference"]["backend"], "llama.cpp")

    def test_lan_host_without_backend_stays_local_loopback(self) -> None:
        out = apply_listen_policy({"inference": {"host": "192.168.1.50", "port": 8080}})
        self.assertEqual(out["inference"]["host"], "127.0.0.1")
        self.assertEqual(out["inference"]["backend"], "llama.cpp")

    def test_lan_host_is_kept_as_remote_client(self) -> None:
        out = apply_listen_policy({"inference": {"backend": "openai-compat", "host": "192.168.1.50", "port": 8080}})
        self.assertEqual(out["inference"]["host"], "192.168.1.50")
        self.assertEqual(out["inference"]["backend"], "openai-compat")
        self.assertTrue(is_remote_inference({"host": "192.168.1.50", "port": 8080, "backend": "openai-compat"}))

    def test_base_url_marks_remote_and_normalizes_v1(self) -> None:
        self.assertEqual(normalize_base_url("http://10.0.0.9:9000"), "http://10.0.0.9:9000/v1")
        self.assertEqual(normalize_base_url("http://10.0.0.9:9000/v1/"), "http://10.0.0.9:9000/v1")
        out = apply_listen_policy({"inference": {"backend": "llama.cpp", "host": "127.0.0.1", "base_url": "10.0.0.9:9000"}})
        self.assertEqual(out["inference"]["backend"], "openai-compat")
        self.assertEqual(out["inference"]["host"], "10.0.0.9")
        self.assertEqual(out["inference"]["port"], 9000)
        self.assertEqual(out["inference"]["base_url"], "http://10.0.0.9:9000/v1")

    def test_env_base_url_overrides_runtime_not_listen_policy(self) -> None:
        os.environ["JARVIS_INFERENCE_BASE_URL"] = "http://10.0.0.8:1234"
        file_out = apply_listen_policy({"inference": {"backend": "llama.cpp", "host": "127.0.0.1"}})
        self.assertEqual(file_out["inference"]["backend"], "llama.cpp")
        self.assertEqual(file_out["inference"]["host"], "127.0.0.1")
        settings = AppSettings.model_validate(file_out)
        self.assertEqual(inference_base_url(settings), "http://10.0.0.8:1234/v1")
        self.assertTrue(is_remote_inference(settings))

    def test_save_does_not_persist_env_overlay(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-qc6-"))
        settings_file = tmp / "settings.json"
        default_file = tmp / "default.json"
        default_file.write_text(
            json.dumps({"inference": {"backend": "llama.cpp", "host": "127.0.0.1", "port": 8088}}),
            encoding="utf-8",
        )
        settings_file.write_text(
            json.dumps({"inference": {"backend": "llama.cpp", "host": "127.0.0.1"}}),
            encoding="utf-8",
        )
        os.environ["JARVIS_INFERENCE_BASE_URL"] = "http://10.0.0.9:9000"
        from app.config import load_settings

        with patch("app.config.settings_path", lambda: settings_file):
            with patch("app.config.default_config_path", lambda: default_file):
                with patch("app.backup.snapshot", lambda **_kwargs: None):
                    loaded = load_settings()
                    self.assertEqual(loaded.inference.host, "127.0.0.1")
                    self.assertNotIn("10.0.0.9", loaded.inference.base_url or "")
                    self.assertTrue(is_remote_inference(loaded))
                    save_settings(loaded)
        dumped = json.loads(settings_file.read_text(encoding="utf-8"))
        blob = json.dumps(dumped)
        self.assertNotIn("10.0.0.9", blob)
        self.assertNotIn("9000", blob)
        self.assertEqual(dumped["inference"].get("backend", "llama.cpp"), "llama.cpp")

    def test_save_settings_strips_api_key(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-t25-"))
        settings = AppSettings()
        with patch("app.config.settings_path", lambda: tmp / "settings.json"):
            with patch("app.backup.snapshot", lambda **_kwargs: None):
                with patch.object(
                    AppSettings,
                    "model_dump",
                    return_value={"inference": {"api_key": "secret-key", "host": "127.0.0.1"}, "mcp_servers": []},
                ):
                    save_settings(settings)
        dumped = (tmp / "settings.json").read_text(encoding="utf-8")
        self.assertNotIn("secret-key", dumped)
        self.assertNotIn("api_key", dumped)


class RemoteManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved = {key: os.environ.pop(key, None) for key in INFERENCE_ENV}

    def tearDown(self) -> None:
        for key in INFERENCE_ENV:
            os.environ.pop(key, None)
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def _remote_settings(self) -> AppSettings:
        return AppSettings.model_validate(
            {
                "inference": {
                    "backend": "openai-compat",
                    "host": "192.168.1.50",
                    "port": 8080,
                    "base_url": "http://192.168.1.50:8080/v1",
                    "model": "Qwen3.5-27B",
                }
            }
        )

    async def test_remote_load_does_not_spawn_llama(self) -> None:
        mgr = InferenceManager()
        settings = self._remote_settings()
        with patch.object(OpenAICompatProvider, "health", new=AsyncMock(return_value=True)):
            with patch("app.inference.manager.kill_llama_on_port") as kill:
                with patch("app.inference.manager.asyncio.create_subprocess_exec") as spawn:
                    state = await mgr.load(settings)
        self.assertTrue(state.loaded)
        self.assertTrue(state.remote)
        self.assertIsNone(state.pid)
        self.assertEqual(state.backend, "openai-compat")
        self.assertEqual(mgr.provider.base_url, "http://192.168.1.50:8080/v1")
        spawn.assert_not_called()
        kill.assert_called()

    async def test_remote_load_does_not_need_gguf(self) -> None:
        mgr = InferenceManager()
        settings = self._remote_settings()
        with patch.object(OpenAICompatProvider, "health", new=AsyncMock(return_value=True)):
            with patch("app.inference.manager.kill_llama_on_port"):
                with patch("app.inference.manager.model_paths", return_value={"root": Path("/missing"), "mmproj": Path("/missing")}):
                    state = await mgr.load(settings)
        self.assertTrue(state.loaded)

    async def test_remote_unload_does_not_kill_local_port(self) -> None:
        mgr = InferenceManager()
        settings = self._remote_settings()
        with patch.object(OpenAICompatProvider, "health", new=AsyncMock(return_value=True)):
            with patch("app.inference.manager.kill_llama_on_port"):
                await mgr.load(settings)
        with patch("app.inference.manager.kill_llama_on_port") as kill:
            await mgr.unload()
        kill.assert_not_called()
        self.assertFalse(mgr.state.loaded)
        self.assertIsNone(mgr.provider)

    async def test_unreachable_remote_raises(self) -> None:
        mgr = InferenceManager()
        settings = self._remote_settings()
        with patch.object(OpenAICompatProvider, "health", new=AsyncMock(return_value=False)):
            with patch("app.inference.manager.kill_llama_on_port"):
                with self.assertRaises(RuntimeError) as raised:
                    await mgr.load(settings)
        self.assertIn("192.168.1.50", str(raised.exception))
        self.assertFalse(mgr.state.loaded)

    async def test_local_load_still_requires_gguf(self) -> None:
        mgr = InferenceManager()
        settings = AppSettings()
        self.assertFalse(is_remote_inference(settings))
        with patch("app.inference.manager.model_paths", return_value={"root": Path("/missing-gguf"), "mmproj": Path("/missing")}):
            with self.assertRaises(FileNotFoundError):
                await mgr.load(settings)


class SettingsRemotePutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved = {key: os.environ.pop(key, None) for key in INFERENCE_ENV}

    def tearDown(self) -> None:
        for key in INFERENCE_ENV:
            os.environ.pop(key, None)
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    async def test_settings_put_remote_host(self) -> None:
        from app.api.settings import SettingsUpdate, update_settings

        stored = AppSettings()

        def fake_load() -> AppSettings:
            return stored

        with patch("app.api.settings.load_settings", fake_load):
            with patch("app.api.settings.save_settings", lambda _settings: None):
                with patch("app.api.settings.REGISTRY.apply_settings", lambda _settings: None):
                    payload = await update_settings(
                        SettingsUpdate(
                            inference_backend="openai-compat",
                            inference_host="192.168.1.50",
                            inference_port=8080,
                            inference_base_url="http://192.168.1.50:8080/v1",
                            inference_model="Qwen3.5-27B",
                        )
                    )
        self.assertEqual(stored.inference.backend, "openai-compat")
        self.assertEqual(stored.inference.host, "192.168.1.50")
        self.assertEqual(stored.inference.port, 8080)
        self.assertTrue(payload["inference_remote"])
        self.assertNotIn("api_key", payload.get("inference") or {})


if __name__ == "__main__":
    unittest.main()
