"""RFC-0195 Wave A seat 3 — humanoid-at-rest identity (RFC-0175 / RFC-0194 residuals)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _run_node(*files: str) -> None:
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--test", *files],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_presence_rest_identity_unit_suite():
    _run_node(
        "presence-rest-identity.test.mjs",
        "presence-lifecycle.test.mjs",
        "presence-silhouette.test.mjs",
    )


def test_no_test_requires_idle_morph_zero():
    for name in (
        "presence-lifecycle.test.mjs",
        "presence-silhouette.test.mjs",
        "presence-rest-identity.test.mjs",
    ):
        src = (FRONTEND / name).read_text(encoding="utf-8")
        assert 'assert.equal(lifecycle.lifecycleMorphTarget("idle"), 0)' not in src
        assert "lifecycleMorphTarget(\"idle\")) === 0" not in src


def test_rest_pose_and_framing_wired_in_product():
    lifecycle = (FRONTEND / "src/presence/presenceLifecycle.ts").read_text(encoding="utf-8")
    cloud = (FRONTEND / "src/presence/renderers/morphableOrbCloud.ts").read_text(
        encoding="utf-8"
    )
    stage = (FRONTEND / "src/presence/renderers/MorphablePresenceStage.tsx").read_text(
        encoding="utf-8"
    )
    silhouette = (FRONTEND / "src/presence/presenceSilhouette.ts").read_text(encoding="utf-8")
    quality = (FRONTEND / "src/presence/presenceQuality.ts").read_text(encoding="utf-8")

    assert "REST_TIGHTNESS = 0.82" in lifecycle
    assert "lifecycleMorphBlend" in lifecycle
    assert "restAttractGain" in lifecycle
    assert "buildRestSilhouette" in cloud
    assert "uRestTightness" in cloud
    assert "restHalo" in cloud
    assert "anchorRestAndFigure" in cloud
    assert "unionPresencePositions" in stage
    assert "restAttractGain" in stage
    assert "evaluateRestIdentity" in silhouette
    assert "identityOnLookAtAfterFit" in quality
    assert "unionPresencePositions" in quality
