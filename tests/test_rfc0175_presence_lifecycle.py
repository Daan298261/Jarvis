"""RFC-0175 amend (2026-09-25): one-presence free→humanoid lifecycle."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_presence_lifecycle_unit_suite():
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--test", "presence-lifecycle.test.mjs"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_lifecycle_is_not_galaxy_gated_in_the_host():
    host = (FRONTEND / "src/presence/PresenceHost.tsx").read_text(encoding="utf-8")
    stage = (FRONTEND / "src/presence/renderers/MorphablePresenceStage.tsx").read_text(encoding="utf-8")
    neural = (FRONTEND / "src/presence/renderers/NeuralCloudPresence.tsx").read_text(encoding="utf-8")
    neural_host = (FRONTEND / "src/presence/renderers/NeuralPresence.tsx").read_text(encoding="utf-8")
    particle = (FRONTEND / "src/presence/renderers/ParticleBustPresence.tsx").read_text(encoding="utf-8")
    humanoid = (FRONTEND / "src/presence/renderers/HumanoidPresence.tsx").read_text(encoding="utf-8")
    attention = (FRONTEND / "src/presence/presenceAttention.ts").read_text(encoding="utf-8")

    assert 'resolved.effective === "none" && staticFallback' in host
    assert "MorphablePresenceStage" not in host
    assert "shapeId={shapeId}" in host
    assert host.count("shapeId={shapeId}") >= 3
    assert "MorphablePresenceStage" in neural
    assert "NeuralCloudPresence" in neural_host
    assert "MorphablePresenceStage" in particle
    assert "MorphablePresenceStage" in humanoid
    assert "setLifecycleTarget" in stage
    assert "lifecycleMorphTarget" in stage
    lifecycle_block = stage.split("system.setLifecycleTarget", 1)[1].split("system.tick", 1)[0]
    assert "galaxy" not in lifecycle_block
    assert "requestedPresence" not in lifecycle_block
    assert "resolvePresenceAttract" in attention
    assert attention.count("navigator.mediaDevices.getUserMedia") == 1
