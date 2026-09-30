"""RFC-0195 Wave A seat 1 — one presence stage + APEX UI copy (Decision 3 / RFC-0136)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_presence_stage_contract_suite():
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--test", "presence-stage-contract.test.mjs"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_appearance_pane_apex_label_and_neural_value():
    pane = (FRONTEND / "src/settings/AppearanceSettingsPane.tsx").read_text(encoding="utf-8")
    assert "APEX UI · orb + graph" in pane
    assert 'requestedPresence: "neural"' in pane
    assert "Neural HUD" not in pane
    assert "separately hosted private humanoid" in pane
