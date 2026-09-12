from __future__ import annotations

from pathlib import Path

from app.agent.docs_first_grounding import search_internal_references


ROOT = Path(__file__).resolve().parents[1]


def test_humanoid_runtime_help_is_indexed_by_docs_first_grounding():
    hits = search_internal_references("How do I install the humanoid runtime?")

    assert hits
    assert hits[0].source_path.endswith("humanoid-runtime.md")


def test_humanoid_anatomy_is_stable_during_activity_and_pointer_tracking():
    renderer = (
        ROOT / "frontend/src/presence/renderers/morphableOrbCloud.ts"
    ).read_text(encoding="utf-8")

    assert "float dissolve = loose * smoothstep" in renderer
    assert "pointerFalloff * loose * uPointerStrength" in renderer
    assert "const figureBudget = Math.round(82000 * density)" in renderer


def test_humanoid_face_uses_distributed_heat_without_a_chest_orb():
    bust = (
        ROOT / "frontend/src/presence/renderers/shapes/humanoidBust.ts"
    ).read_text(encoding="utf-8")

    assert "Math.round(18000 * density)" in bust
    assert "A diffuse amber volume behind the scan bands" in bust
    assert "emit(0, -1.28" not in bust
