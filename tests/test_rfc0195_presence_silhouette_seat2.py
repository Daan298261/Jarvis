"""RFC-0195 Wave A seat 2 — rest tightness, framing landmarks, bloom/overexposure."""

from __future__ import annotations

from pathlib import Path

from tests.presence_node import run_presence_node_suite

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _run_node(*files: str) -> None:
    run_presence_node_suite(*files, timeout=180)


def test_presence_silhouette_unit_suite():
    _run_node("presence-silhouette.test.mjs", "presence-lifecycle.test.mjs")


def test_no_test_requires_idle_morph_zero():
    lifecycle = (FRONTEND / "presence-lifecycle.test.mjs").read_text(encoding="utf-8")
    silhouette = (FRONTEND / "presence-silhouette.test.mjs").read_text(encoding="utf-8")
    for src in (lifecycle, silhouette):
        assert 'assert.equal(lifecycle.lifecycleMorphTarget("idle"), 0)' not in src
        assert "lifecycleMorphTarget(\"idle\")) === 0" not in src
        assert 'assert.equal(lifecycle.lifecycleMorphTarget("waiting"), 0)' not in src
        assert 'assert.equal(lifecycle.lifecycleMorphTarget("offline"), 0)' not in src
    module = (FRONTEND / "src/presence/presenceLifecycle.ts").read_text(encoding="utf-8")
    assert "REST_TIGHTNESS = 0.82" in module
    assert "0.72" in module and "0.92" in module
    assert "lifecycleMorphTarget" in module
    assert "isRestPresencePhase" in module


def test_bloom_and_landmark_contract_in_stage():
    stage = (FRONTEND / "src/presence/renderers/MorphablePresenceStage.tsx").read_text(
        encoding="utf-8"
    )
    quality = (FRONTEND / "src/presence/presenceQuality.ts").read_text(encoding="utf-8")
    assert "resolvePresenceBloom" in stage
    assert "resolveDotAppearance" in stage
    assert "motifSafeAccentHex" in stage
    assert "framing?.landmarks" in stage
    assert "presenceLookAtFromFit" in stage
    assert "dataset.restTightness" in stage
    assert "PRESENCE_OVEREXPOSURE_RATIO_MAX" in quality
    assert "PRESENCE_EDGE_CONTRAST_MIN" in quality
    cloud = (FRONTEND / "src/presence/renderers/morphableOrbCloud.ts").read_text(
        encoding="utf-8"
    )
    assert "REST_TIGHTNESS" in cloud
    assert "clampLifecycleMorph" in cloud
    assert "coreHot" in cloud
