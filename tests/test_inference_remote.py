from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings, InferenceSettings
from app.inference.endpoint import (
    apply_inference_settings,
    inference_base_url,
    inference_model_name,
    is_remote_inference,
    is_remote_inference_dict,
    normalize_base_url,
    worker_openai_endpoint,
)
from app.inference.manager import InferenceManager
from app.security import apply_listen_policy


class NormalizeUrlTests(unittest.TestCase):
    def test_adds_v1_and_scheme(self) -> None:
        self.assertEqual(normalize_base_url("192.168.1.50:8088"), "http://192.168.1.50:8088/v1")
        self.assertEqual(normalize_base_url("http://gpu-box:8000/v1"), "http://gpu-box:8000/v1")
        self.assertEqual(normalize_base_url("https://gpu-box/"), "https://gpu-box/v1")
        self.assertEqual(normalize_base_url("file:///tmp"), "")


class RemoteDetectionTests(unittest.TestCase):
    def test_default_is_local(self) -> None:
        self.assertFalse(is_remote_inference(AppSettings()))
        self.assertFalse(is_remote_inference_dict({"backend": "llama.cpp", "host": "127.0.0.1"}))

    def test_llama_cpp_lan_host_is_not_remote(self) -> None:
        self.assertFalse(is_remote_inference_dict({"backend": "llama.cpp", "host": "10.0.0.2"}))

    def test_backend_or_base_url_is_remote(self) -> None:
        self.assertTrue(is_remote_inference_dict({"backend": "openai-compat", "host": "192.168.1.50"}))
        self.assertTrue(is_remote_inference_dict({"backend": "llama.cpp", "base_url": "http://192.168.1.50:8088/v1"}))


class ListenPolicyRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        for key in ("JARVIS_INFERENCE_BACKEND", "JARVIS_INFERENCE_HOST", "JARVIS_INFERENCE_PORT", "JARVIS_INFERENCE_BASE_URL"):
            os.environ.pop(key, None)

    def test_local_llama_host_still_loopback(self) -> None:
        out = apply_listen_policy({"inference": {"host": "10.0.0.2"}})
        self.assertEqual(out["inference"]["host"], "127.0.0.1")
        self.assertEqual(out["inference"]["backend"], "llama.cpp")
        out = apply_listen_policy({"inference": {"host": "0.0.0.0"}})
        self.assertEqual(out["inference"]["host"], "127.0.0.1")

    def test_remote_backend_keeps_lan_host(self) -> None:
        out = apply_listen_policy({"inference": {"backend": "openai-compat", "host": "192.168.1.50", "port": 8088}})
        self.assertEqual(out["inference"]["host"], "192.168.1.50")
        self.assertEqual(out["inference"]["backend"], "openai-compat")

    def test_base_url_keeps_remote_and_sets_backend(self) -> None:
        out = apply_listen_policy({"inference": {"base_url": "http://192.168.1.20:8000"}})
        self.assertEqual(out["inference"]["host"], "192.168.1.20")
        self.assertEqual(out["inference"]["port"], 8000)
        self.assertEqual(out["inference"]["backend"], "openai-compat")
        self.assertTrue(out["inference"]["base_url"].endswith("/v1"))


class InferenceUrlTests(unittest.TestCase):
    def test_local_url_is_loopback_v1(self) -> None:
        self.assertEqual(inference_base_url(AppSettings()), "http://127.0.0.1:8088/v1")

    def test_remote_host_and_env_overlay(self) -> None:
        settings = AppSettings(
            inference=InferenceSettings(backend="openai-compat", host="192.168.1.50", port=8080, model="Qwen3.5-27B")
        )
        self.assertEqual(inference_base_url(settings), "http://192.168.1.50:8080/v1")
        with patch.dict(os.environ, {"JARVIS_INFERENCE_BASE_URL": "http://gpu:9000"}):
            self.assertEqual(inference_base_url(settings), "http://gpu:9000/v1")

    def test_env_backend_makes_settings_remote(self) -> None:
        raw = apply_inference_settings({"backend": "llama.cpp", "host": "127.0.0.1", "port": 8088})
        with patch.dict(os.environ, {"JARVIS_INFERENCE_BACKEND": "openai-compat", "JARVIS_INFERENCE_HOST": "10.8.0.2"}):
            raw = apply_inference_settings({"backend": "llama.cpp", "host": "127.0.0.1", "port": 8088})
        self.assertEqual(raw["backend"], "openai-compat")
        self.assertEqual(raw["host"], "10.8.0.2")

    def test_worker_endpoint_matches_manager(self) -> None:
        settings = AppSettings(
            inference=InferenceSettings(backend="vllm", host="192.168.0.9", port=8000, model="local-qwen")
        )
        base, key, model = worker_openai_endpoint(settings)
        self.assertEqual(base, inference_base_url(settings))
        self.assertEqual(model, "local-qwen")
        self.assertTrue(key)

    def test_model_name_default(self) -> None:
        self.assertEqual(inference_model_name(AppSettings()), "Qwen3.5-9B-Abliterated")

    def test_apply_does_not_mutate_input(self) -> None:
        original = {"backend": "llama.cpp", "host": "10.0.0.2"}
        snapshot = dict(original)
        apply_inference_settings(original, env=False)
        self.assertEqual(original, snapshot)

    def test_cmdline_port_ignores_ctx_size(self) -> None:
        from app.inference.llama_process import _cmdline_has_port

        cmd = ["llama-server", "--port", "8090", "--ctx-size", "8088"]
        self.assertFalse(_cmdline_has_port(cmd, 8088))
        self.assertTrue(_cmdline_has_port(cmd, 8090))
        self.assertFalse(_cmdline_has_port(["llama-server", "--ctx-size", "8088"], 8088))


class RemoteLoadTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_load_skips_local_model_and_spawn(self) -> None:
        settings = AppSettings(
            inference=InferenceSettings(
                backend="openai-compat",
                host="192.168.1.50",
                port=8088,
                base_url="http://192.168.1.50:8088/v1",
                model="Qwen3.5-27B",
            )
        )
        manager = InferenceManager()
        provider = SimpleNamespace(health=AsyncMock(return_value=True), base_url="http://192.168.1.50:8088/v1", model="Qwen3.5-27B")
        with (
            patch("app.inference.manager.OpenAICompatProvider", return_value=provider) as ctor,
            patch("app.inference.manager.kill_llama_on_port") as killer,
            patch("asyncio.create_subprocess_exec", new=AsyncMock()) as spawn,
        ):
            state = await manager.load(settings)
        self.assertTrue(state.loaded)
        self.assertTrue(state.remote)
        self.assertIsNone(state.pid)
        self.assertEqual(state.backend, "openai-compat")
        ctor.assert_called_once()
        self.assertEqual(ctor.call_args[0][0], "http://192.168.1.50:8088/v1")
        spawn.assert_not_called()
        killer.assert_called()

    async def test_remote_load_fails_when_unreachable(self) -> None:
        settings = AppSettings(
            inference=InferenceSettings(backend="openai-compat", host="192.168.1.50", base_url="http://192.168.1.50:8088/v1")
        )
        manager = InferenceManager()
        provider = SimpleNamespace(health=AsyncMock(return_value=False), base_url="http://192.168.1.50:8088/v1", model="Qwen3.5-27B")
        with (
            patch("app.inference.manager.OpenAICompatProvider", return_value=provider),
            patch("app.inference.manager.kill_llama_on_port"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unreachable"):
                await manager.load(settings)
        self.assertFalse(manager.state.loaded)

    async def test_unload_remote_does_not_kill_local_llama(self) -> None:
        manager = InferenceManager()
        manager.state.loaded = True
        manager.state.remote = True
        manager.state.backend = "openai-compat"
        manager.provider = SimpleNamespace()
        with patch("app.inference.manager.kill_llama_on_port") as killer:
            await manager.unload()
        killer.assert_not_called()
        self.assertFalse(manager.state.loaded)
        self.assertFalse(manager.state.remote)

    async def test_snapshot_loaded_false_when_unhealthy(self) -> None:
        manager = InferenceManager()
        manager.state.loaded = True
        manager.state.profile = "fast"
        manager.provider = SimpleNamespace(
            health=AsyncMock(return_value=False),
            model="Qwen3.5-27B",
            base_url="http://127.0.0.1:8088/v1",
        )
        with patch.object(manager, "refresh_resources", new=AsyncMock()):
            snapshot = await manager.snapshot(AppSettings())
        self.assertFalse(snapshot["loaded"])
        self.assertFalse(snapshot["healthy"])

    async def test_ready_for_profile_requires_health(self) -> None:
        from app.inference.profiles import resolve_profile

        manager = InferenceManager()
        profile = resolve_profile("fast")
        manager.state.loaded = True
        manager.state.profile = "fast"
        manager.state.thinking_at_process = profile.thinking
        manager.provider = SimpleNamespace(health=AsyncMock(return_value=False))
        self.assertFalse(await manager.ready_for_profile(profile))
        manager.provider.health = AsyncMock(return_value=True)
        self.assertTrue(await manager.ready_for_profile(profile))


class FrontendRemoteUiTests(unittest.TestCase):
    def test_model_page_connects_same_task_provider(self) -> None:
        source = (ROOT / "frontend" / "src" / "pages" / "Model.tsx").read_text(encoding="utf-8")
        self.assertIn("inference_backend", source)
        self.assertIn("openai-compat", source)
        self.assertIn("/api/model/load", source)
        self.assertIn("JARVIS_INFERENCE_API_KEY", source)

    def test_settings_page_has_inference_server(self) -> None:
        source = (ROOT / "frontend" / "src" / "pages" / "Settings.tsx").read_text(encoding="utf-8")
        self.assertIn("Inference server", source)
        self.assertIn("inference_base_url", source)


if __name__ == "__main__":
    unittest.main()
