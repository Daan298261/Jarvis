from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.inference.llama_process import launch_matches_profile, reasoning_flag
from app.inference.manager import InferenceManager
from app.inference.profiles import PROFILES
from app.config import AppSettings


class FastReasoningLaunchTests(unittest.TestCase):
    def test_fast_reasoning_flag_is_off(self) -> None:
        self.assertEqual(reasoning_flag(False), "off")
        self.assertEqual(reasoning_flag(PROFILES["fast"].thinking), "off")
        self.assertEqual(reasoning_flag(PROFILES["balanced"].thinking), "on")

    def test_running_server_with_reasoning_on_does_not_match_fast(self) -> None:
        info = {
            "reasoning": "on",
            "model": r"C:\models\Qwen3.5-27B-Q4_K_M.gguf",
            "ctx": 32768,
        }
        self.assertFalse(launch_matches_profile(info, PROFILES["fast"]))
        self.assertTrue(launch_matches_profile(info, PROFILES["balanced"]))

    def test_running_server_with_reasoning_off_matches_fast(self) -> None:
        info = {
            "reasoning": "off",
            "model": r"C:\models\Qwen3.5-27B-Q4_K_M.gguf",
            "ctx": 16384,
        }
        self.assertTrue(launch_matches_profile(info, PROFILES["fast"]))
        self.assertFalse(launch_matches_profile(info, PROFILES["balanced"]))

    def test_build_args_fast_starts_with_reasoning_off(self) -> None:
        manager = InferenceManager()
        if not manager.llama_server_path().exists():
            self.skipTest("llama-server.exe not installed")
        args = manager.build_args(AppSettings(), PROFILES["fast"])
        self.assertIn("--reasoning", args)
        self.assertEqual(args[args.index("--reasoning") + 1], "off")
        balanced = manager.build_args(AppSettings(), PROFILES["balanced"])
        self.assertEqual(balanced[balanced.index("--reasoning") + 1], "on")


if __name__ == "__main__":
    unittest.main()
