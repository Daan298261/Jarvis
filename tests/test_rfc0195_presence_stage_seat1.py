"""RFC-0195 Wave A seat 1 — one presence stage + APEX UI copy (Decision 3 / RFC-0136)."""

from __future__ import annotations

from pathlib import Path

from tests.presence_node import run_presence_node_suite

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_presence_stage_contract_suite():
    run_presence_node_suite("presence-stage-contract.test.mjs", timeout=120)


def test_appearance_pane_apex_label_and_neural_value():
    pane = (FRONTEND / "src/settings/AppearanceSettingsPane.tsx").read_text(encoding="utf-8")
    assert "APEX UI · orb + graph" in pane
    assert 'requestedPresence: "neural"' in pane
    assert "Neural HUD" not in pane
    assert "separately hosted private humanoid" in pane
