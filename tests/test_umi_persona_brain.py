"""Umi named persona + Ollama brain runtime profile."""

from __future__ import annotations

from app.inference.model_stack import MODEL_CATALOG, recommended_specialist_runtime_profiles
from app.inference.runtime_profiles import get_runtime_profile, reset_runtime_profiles
from app.persona.named_persona import CATALOG, ROSTER_IDS
from app.persona.persona_brain import UMI_OLLAMA_MODEL, brain_runtime_name_for_persona


def test_umi_persona_in_roster():
    assert "umi" in ROSTER_IDS
    row = CATALOG["umi"]
    assert row.label == "Umi"
    assert row.voice_profile_id == "pocket_tts_alba_en_v1"


def test_umi_brain_runtime_catalog():
    entry = MODEL_CATALOG["umi-opus-9b"]
    assert entry.provider == "ollama"
    assert entry.model_id == UMI_OLLAMA_MODEL
    assert "agentic" in entry.capability_tags
    assert entry.inference_profile == "balanced"


def test_umi_runtime_profile_merges_into_registry():
    reset_runtime_profiles()
    names = {profile.name for profile in recommended_specialist_runtime_profiles()}
    assert "umi-opus-9b" in names
    profile = get_runtime_profile("umi-opus-9b")
    assert profile is not None
    assert profile.provider == "ollama"
    assert profile.model == UMI_OLLAMA_MODEL
    assert profile.model_profile == "balanced"


def test_persona_brain_mapping():
    assert brain_runtime_name_for_persona("umi") == "umi-opus-9b"
    assert brain_runtime_name_for_persona("anzu") is None
