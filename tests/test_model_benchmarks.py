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

from app.config import AppSettings
from app.inference.benchmarks import (
    latest_for_profile,
    list_benchmarks,
    load_benchmarks,
    record_benchmark,
)
from app.inference.manager import InferenceManager, InferenceState
from app.providers.base import ChatResult


class BenchmarkStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t18-"))
        self.path = self.tmp / "model_benchmarks.json"
        self.patcher = patch("app.inference.benchmarks.benchmark_store_path", lambda: self.path)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()

    def test_record_persists_tok_s_vram_and_load_time(self) -> None:
        sample = record_benchmark(
            profile="fast",
            quant="Q4_K_M",
            tokens_per_second=10.8,
            prompt_tokens_per_second=32.1,
            vram_used_mib=15366,
            load_time_seconds=41.2,
            source="load",
        )
        assert sample is not None
        latest = latest_for_profile("fast")
        assert latest is not None
        self.assertEqual(latest["tokens_per_second"], 10.8)
        self.assertEqual(latest["vram_used_mib"], 15366)
        self.assertEqual(latest["load_time_seconds"], 41.2)
        self.assertEqual(len(load_benchmarks()), 1)
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(stored["profiles"]["fast"]["tokens_per_second"], 10.8)

    def test_later_tok_s_keeps_previous_load_time(self) -> None:
        record_benchmark(profile="fast", load_time_seconds=40.0, vram_used_mib=15000, source="load")
        updated = record_benchmark(
            profile="fast",
            tokens_per_second=11.2,
            prompt_tokens_per_second=30.0,
            vram_used_mib=15280,
            source="generation",
        )
        assert updated is not None
        self.assertEqual(updated["tokens_per_second"], 11.2)
        self.assertEqual(updated["load_time_seconds"], 40.0)
        self.assertEqual(updated["vram_used_mib"], 15280)

    def test_vram_update_does_not_wipe_tok_s(self) -> None:
        record_benchmark(profile="fast", tokens_per_second=10.7, load_time_seconds=12.5, vram_used_mib=15000)
        row = record_benchmark(profile="fast", vram_used_mib=15280, source="attach")
        assert row is not None
        self.assertEqual(row["tokens_per_second"], 10.7)
        self.assertEqual(row["load_time_seconds"], 12.5)
        self.assertEqual(row["vram_used_mib"], 15280)

    def test_list_orders_known_profiles(self) -> None:
        record_benchmark(profile="quality", tokens_per_second=8.1)
        record_benchmark(profile="fast", tokens_per_second=10.7)
        record_benchmark(profile="balanced", tokens_per_second=9.4)
        names = [row["profile"] for row in list_benchmarks()]
        self.assertEqual(names, ["fast", "balanced", "quality"])

    def test_empty_sample_is_not_written(self) -> None:
        self.assertIsNone(record_benchmark(profile="fast", source="generation"))
        self.assertEqual(load_benchmarks(), [])


class InferenceBenchmarkPersistTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t18-mgr-"))
        self.store = patch(
            "app.inference.benchmarks.benchmark_store_path",
            lambda: self.tmp / "model_benchmarks.json",
        )
        self.store.start()
        self.manager = InferenceManager()
        self.manager.state = InferenceState(profile="fast", quant="Q4_K_M", context_size=16384, loaded=True)

        async def _noop_refresh():
            return None

        self.manager.refresh_resources = _noop_refresh  # type: ignore[method-assign]

    async def asyncTearDown(self) -> None:
        self.store.stop()

    async def test_record_timings_persists_and_survives_new_manager(self) -> None:
        self.manager.state.load_time_seconds = 38.5
        self.manager.state.vram_used_mib = 15200
        await self.manager.record_timings({"predicted_per_second": 10.74, "prompt_per_second": 31.2})
        self.assertEqual(self.manager.state.generation_tps, 10.74)
        latest = latest_for_profile("fast")
        assert latest is not None
        self.assertEqual(latest["tokens_per_second"], 10.74)
        self.assertEqual(latest["vram_used_mib"], 15200)
        self.assertEqual(latest["load_time_seconds"], 38.5)

        restored = InferenceManager()
        restored.state.profile = "fast"
        restored._hydrate_from_store()
        self.assertEqual(restored.state.generation_tps, 10.74)
        self.assertEqual(restored.state.vram_used_mib, 15200)
        self.assertEqual(restored.state.load_time_seconds, 38.5)

        async def fake_refresh():
            restored.state.vram_used_mib = 999

        restored.refresh_resources = fake_refresh  # type: ignore[method-assign]
        snapshot = await restored.snapshot(AppSettings())
        self.assertFalse(restored.state.loaded)
        self.assertEqual(snapshot["tokens_per_second"], 10.74)
        self.assertEqual(snapshot["prompt_tokens_per_second"], 31.2)
        self.assertEqual(snapshot["vram_used_mib"], 15200)
        self.assertEqual(snapshot["load_time_seconds"], 38.5)
        self.assertTrue(snapshot["metrics_persisted"])
        self.assertTrue(snapshot["benchmark_persisted_at"])
        self.assertEqual(snapshot["benchmarks"][0]["tokens_per_second"], 10.74)
        self.assertEqual(snapshot["benchmarks"][0]["profile"], "fast")

    async def test_unload_does_not_delete_store(self) -> None:
        self.manager.state.load_time_seconds = 10.02
        self.manager.state.vram_used_mib = 15280
        await self.manager.record_timings({"predicted_per_second": 10.69, "prompt_per_second": 68.25})
        with patch("app.inference.manager.kill_llama_on_port"):
            await self.manager.unload()
        latest = latest_for_profile("fast")
        assert latest is not None
        self.assertEqual(latest["tokens_per_second"], 10.69)
        self.assertEqual(latest["vram_used_mib"], 15280)
        self.assertEqual(latest["load_time_seconds"], 10.02)

    async def test_run_benchmark_requires_loaded_model(self) -> None:
        self.manager.state.loaded = False
        with self.assertRaisesRegex(RuntimeError, "not loaded"):
            await self.manager.run_benchmark(AppSettings())

    async def test_run_benchmark_records_timings(self) -> None:
        async def fake_chat(*args, **kwargs):
            return ChatResult(content="ready", timings={"predicted_per_second": 9.5, "prompt_per_second": 28.0})

        async def fake_health():
            return True

        self.manager.provider = SimpleNamespace(chat=fake_chat, health=fake_health)
        self.manager.state.loaded = True
        self.manager.state.load_time_seconds = 42.0
        snapshot = await self.manager.run_benchmark(AppSettings())
        self.assertEqual(snapshot["tokens_per_second"], 9.5)
        self.assertEqual(latest_for_profile("fast")["load_time_seconds"], 42.0)
        self.assertEqual(latest_for_profile("fast")["source"], "generation")


if __name__ == "__main__":
    unittest.main()
