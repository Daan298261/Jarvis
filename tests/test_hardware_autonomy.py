from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.autonomy import PAUSE_EVEN_WHEN_AUTONOMOUS, catalog, resolve_autonomy
from app.agent.loop import _environment_block
from app.config import AppSettings
from app.hardware import HardwareInfo, hardware_view, recommend_inference
from app.tools.base import RiskLevel
from app.tools.safety import classify_command, needs_confirmation
from app.tools.terminal import TerminalTool


def _hw(**overrides) -> HardwareInfo:
    base = dict(
        os_name="Windows",
        os_version="10.0.26200",
        os_caption="Microsoft Windows 11 Pro",
        architecture="AMD64",
        cpu_name="Intel(R) Core(TM) i7-14700KF",
        cpu_cores=20,
        cpu_threads=28,
        ram_total_gb=63.8,
        ram_available_gb=40.0,
        gpu_name="NVIDIA GeForce RTX 5070 Ti",
        gpu_architecture="Blackwell",
        gpu_compute_cap="12.0",
        vram_total_mib=16303,
        vram_free_mib=14000,
        nvidia_driver="581.80",
        cuda_version="13.0",
        disk_free_gb=337.0,
        disk_total_gb=930.0,
        python_version="3.12.0",
        node_installed=True,
        git_installed=True,
        docker_installed=False,
        office_installed=False,
        wsl_available=True,
    )
    base.update(overrides)
    return HardwareInfo(**base)


class AutonomyCatalogTests(unittest.TestCase):
    def test_three_modes_match_the_plan(self) -> None:
        modes = {item["name"]: item for item in catalog()}
        self.assertEqual(set(modes), {"interactive", "trusted", "autonomous"})
        self.assertIn("consequential", modes["interactive"]["description"].lower())
        self.assertIn("normal work", modes["trusted"]["description"].lower())
        self.assertIn("high-impact", modes["trusted"]["description"].lower())
        self.assertIn("without repeated interaction", modes["autonomous"]["description"].lower())
        self.assertIn("disk formatting", PAUSE_EVEN_WHEN_AUTONOMOUS)
        self.assertIn("purchases", PAUSE_EVEN_WHEN_AUTONOMOUS)
        self.assertTrue(any("externally" in item for item in PAUSE_EVEN_WHEN_AUTONOMOUS))
        for item in catalog():
            self.assertEqual(item["pause_even_when_autonomous"], list(PAUSE_EVEN_WHEN_AUTONOMOUS))

    def test_resolve_aliases_and_unknown(self) -> None:
        self.assertEqual(resolve_autonomy("ask").name, "interactive")
        self.assertEqual(resolve_autonomy("auto").name, "autonomous")
        self.assertEqual(resolve_autonomy("nope").name, "trusted")
        self.assertEqual(resolve_autonomy(None).name, "trusted")

    def test_confirmation_bands(self) -> None:
        self.assertTrue(needs_confirmation("interactive", RiskLevel.MEDIUM))
        self.assertFalse(needs_confirmation("interactive", RiskLevel.LOW))
        self.assertFalse(needs_confirmation("trusted", RiskLevel.MEDIUM))
        self.assertTrue(needs_confirmation("trusted", RiskLevel.HIGH))
        self.assertFalse(needs_confirmation("autonomous", RiskLevel.HIGH))
        self.assertTrue(needs_confirmation("autonomous", RiskLevel.IRREVERSIBLE))

    def test_command_classification_matches_stop_list(self) -> None:
        self.assertEqual(classify_command("format C:"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("diskpart"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("wbadmin delete backup"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("net user alice Secret123"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("Send-MailMessage -To a@b.com"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("disable defender"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("stripe checkout buy now"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("python purchase.py"), RiskLevel.MEDIUM)
        self.assertEqual(classify_command(r"type C:\temp\passwd"), RiskLevel.MEDIUM)
        self.assertEqual(classify_command("passwd alice"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("rm -rf /"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command("rm -rf /tmp/build"), RiskLevel.HIGH)
        self.assertEqual(classify_command(r"Remove-Item -Recurse C:\Windows\System32"), RiskLevel.IRREVERSIBLE)
        self.assertEqual(classify_command(r"Remove-Item -Recurse C:\Users\daanv\Documents\foo"), RiskLevel.HIGH)
        self.assertEqual(classify_command("git push --force"), RiskLevel.HIGH)
        self.assertEqual(classify_command("pytest tests"), RiskLevel.MEDIUM)

    def test_autonomous_pauses_only_for_irreversible_commands(self) -> None:
        self.assertTrue(needs_confirmation("autonomous", RiskLevel.MEDIUM, "format C:"))
        self.assertFalse(needs_confirmation("autonomous", RiskLevel.MEDIUM, "pytest"))
        self.assertTrue(needs_confirmation("trusted", RiskLevel.MEDIUM, "rm -rf build"))
        self.assertFalse(needs_confirmation("autonomous", RiskLevel.MEDIUM, "rm -rf build"))
        self.assertFalse(needs_confirmation("trusted", RiskLevel.MEDIUM, "dir"))

    def test_terminal_is_medium_so_trusted_runs_ordinary_shell(self) -> None:
        self.assertEqual(TerminalTool.risk, RiskLevel.MEDIUM)
        self.assertFalse(needs_confirmation("trusted", TerminalTool.risk, "python -m pytest"))
        self.assertTrue(needs_confirmation("interactive", TerminalTool.risk, "python -m pytest"))

    def test_environment_block_states_autonomy(self) -> None:
        settings = AppSettings(allowed_directories=[str(ROOT)])
        text = _environment_block(settings, "balanced", "autonomous")
        self.assertIn("Autonomous", text)
        self.assertIn("disk format", text.lower())
        self.assertIn("Execution mode: Balanced", text)

    def test_default_config_is_trusted(self) -> None:
        raw = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["autonomy"], "trusted")


class HardwareViewTests(unittest.TestCase):
    def test_labeled_groups_expose_detected_facts(self) -> None:
        view = hardware_view(_hw())
        labels = {group["id"]: group for group in view["groups"]}
        self.assertEqual(set(labels), {"machine", "memory", "gpu", "storage", "software"})
        machine = {item["label"]: item["value"] for item in labels["machine"]["items"]}
        gpu = {item["label"]: item["value"] for item in labels["gpu"]["items"]}
        memory = {item["label"]: item["value"] for item in labels["memory"]["items"]}
        self.assertEqual(machine["OS"], "Microsoft Windows 11 Pro")
        self.assertIn("i7-14700KF", machine["CPU"])
        self.assertIn("20", machine["Cores / threads"])
        self.assertIn("63.8", memory["RAM total"])
        self.assertEqual(gpu["GPU"], "NVIDIA GeForce RTX 5070 Ti")
        self.assertIn("16303", gpu["VRAM total"])
        self.assertEqual(gpu["CUDA"], "13.0")
        self.assertEqual(gpu["NVIDIA driver"], "581.80")
        self.assertEqual(gpu["Architecture"], "Blackwell")
        self.assertIn("Windows 11 Pro", view["summary"])
        self.assertIn("RTX 5070 Ti", view["summary"])
        self.assertIn("Q4_K_M", view["recommendation"])
        self.assertEqual(view["raw"]["vram_total_mib"], 16303)

    def test_recommendation_without_gpu(self) -> None:
        text = recommend_inference(_hw(gpu_name=None, vram_total_mib=None))
        self.assertIn("CPU", text)

    def test_live_detection_has_required_keys(self) -> None:
        from app.hardware import hardware_dict

        raw = hardware_dict(force=True)
        for key in (
            "os_caption",
            "cpu_name",
            "cpu_cores",
            "ram_total_gb",
            "gpu_name",
            "vram_total_mib",
            "nvidia_driver",
            "cuda_version",
            "disk_free_gb",
        ):
            self.assertIn(key, raw)
        self.assertTrue(raw["os_caption"])
        self.assertGreater(raw["ram_total_gb"], 1)


if __name__ == "__main__":
    unittest.main()
