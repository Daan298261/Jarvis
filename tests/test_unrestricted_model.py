from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings
from app.inference.manager import InferenceManager
from app.inference.profiles import (
    ABLITERATED_FOLDER,
    ABLITERATED_Q6,
    OFFICIAL_FOLDER,
    UNRESTRICTED_FOLDER,
    UNRESTRICTED_Q4,
    PROFILES,
    available_profiles,
    model_paths,
    resolve_profile,
)


class UnrestrictedModelProfileTests(unittest.TestCase):
    def test_abliterated_9b_profile_uses_its_own_folder_and_alias(self) -> None:
        profile = PROFILES["abliterated-balanced"]
        paths = model_paths(profile)
        self.assertEqual(paths["root"].name, ABLITERATED_FOLDER)
        self.assertEqual(paths["gguf"].name, ABLITERATED_Q6)
        self.assertEqual(profile.alias, "Qwen3.5-9B-Abliterated")
        self.assertEqual(profile.quant, "Q6_K")

    def test_official_and_unrestricted_live_in_sibling_folders(self) -> None:
        official = model_paths(PROFILES["balanced"])
        unrestricted = model_paths(PROFILES["unrestricted-balanced"])
        self.assertEqual(official["root"].name, OFFICIAL_FOLDER)
        self.assertEqual(unrestricted["root"].name, UNRESTRICTED_FOLDER)
        self.assertNotEqual(official["root"], unrestricted["root"])
        self.assertEqual(unrestricted["gguf"].name, UNRESTRICTED_Q4)
        self.assertTrue(official["gguf"].exists(), "official Q4 GGUF must remain in place")

    def test_unrestricted_profiles_only_listed_when_gguf_exists(self) -> None:
        names = {row.name for row in available_profiles()}
        self.assertIn("fast", names)
        self.assertIn("balanced", names)
        path = model_paths(PROFILES["unrestricted-balanced"])["gguf"]
        if path.exists():
            self.assertIn("unrestricted-balanced", names)
        else:
            self.assertNotIn("unrestricted-balanced", names)

    def test_unrestricted_launch_args_point_at_sibling_gguf(self) -> None:
        manager = InferenceManager()
        if not manager.llama_server_path().exists():
            self.skipTest("llama-server.exe not installed")
        args = manager.build_args(AppSettings(), PROFILES["unrestricted-balanced"])
        model = args[args.index("--model") + 1]
        self.assertIn(UNRESTRICTED_FOLDER, model.replace("/", "\\"))
        self.assertTrue(model.endswith(UNRESTRICTED_Q4))
        self.assertEqual(args[args.index("--alias") + 1], "Qwen3.5-27B-Unrestricted")
        official = manager.build_args(AppSettings(), PROFILES["balanced"])
        official_model = official[official.index("--model") + 1]
        self.assertIn(OFFICIAL_FOLDER, official_model.replace("/", "\\"))
        self.assertNotEqual(Path(model), Path(official_model))

    def test_abliterated_launch_args_include_matching_model_and_projector(self) -> None:
        manager = InferenceManager()
        if not manager.llama_server_path().exists():
            self.skipTest("llama-server.exe not installed")
        args = manager.build_args(AppSettings(), PROFILES["abliterated-balanced"])
        self.assertTrue(args[args.index("--model") + 1].endswith(ABLITERATED_Q6))
        self.assertEqual(args[args.index("--alias") + 1], "Qwen3.5-9B-Abliterated")
        projector = model_paths(PROFILES["abliterated-balanced"])["mmproj"]
        if projector.exists():
            self.assertEqual(Path(args[args.index("--mmproj") + 1]), projector)

    def test_resolve_unrestricted_falls_back_if_missing(self) -> None:
        profile = resolve_profile("unrestricted-quality")
        if not model_paths(PROFILES["unrestricted-balanced"])["gguf"].exists():
            self.assertEqual(profile.family, "official")
        else:
            self.assertEqual(profile.family, "unrestricted")


if __name__ == "__main__":
    unittest.main()
