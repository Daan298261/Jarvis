from __future__ import annotations

import pytest

from app.inference.model_stack import (
    MODEL_CATALOG,
    get_specialist_model,
    list_specialist_models,
    routing_preferences_for_role,
)
from app.inference.runtime_profiles import default_runtime_profiles


def test_specialist_catalog_contains_expected_models():
    assert MODEL_CATALOG["ornith-orchestrator"].model_id == "ornith-ai/Ornith-1.5-9B"
    assert MODEL_CATALOG["qwen38-leader"].model_id == "Qwen/Qwen3.8-27B"
    assert MODEL_CATALOG["redsage-blue"].model_id == "RISys-Lab/RedSage-Qwen3-8B-DPO"
    assert MODEL_CATALOG["imperum-dfir"].model_id == "IMPERUM/Imperum-CybersecurityLLM-v1.0-GGUF"
    assert MODEL_CATALOG["deephat-red"].model_id == "DeepHat/DeepHat-V1-7B"


def test_red_team_recommendation_ships_disabled_and_manual_gated():
    red = get_specialist_model("deephat-red")
    assert red is not None
    assert red.role == "red-team"
    assert red.manual_gate is True
    assert red.ship_runtime_template is True
    runtime = red.runtime_profile()
    assert runtime is not None
    assert runtime.name == "deephat-7b"
    assert runtime.enabled is False
    assert list_specialist_models(role="red-team") == [red]

    profiles = {profile.name: profile for profile in default_runtime_profiles()}
    assert profiles["deephat-7b"].enabled is False


def test_generic_red_team_role_routing_fails_closed():
    with pytest.raises(PermissionError, match="password gate"):
        routing_preferences_for_role("red-team")

    with pytest.raises(PermissionError, match="password gate"):
        routing_preferences_for_role("pentest")


def test_authorized_red_team_role_builds_preferences_only_after_external_gate():
    prefs = routing_preferences_for_role("red-team", allow_manual_gate=True)
    assert prefs.preferred_profiles == ("deephat-7b",)
    assert "red-team" in prefs.required_capabilities
    assert prefs.task_specialization == "red-team"


def test_orchestrator_role_prefers_ornith():
    prefs = routing_preferences_for_role("orchestrator")
    assert prefs.preferred_profiles[0] == "ornith_9b"
    assert prefs.required_capabilities == ("llm_inference", "text")
    assert prefs.task_specialization == "orchestration"


def test_leader_role_prefers_qwen38_then_local_fallbacks():
    prefs = routing_preferences_for_role("leader")
    assert prefs.preferred_profiles == ("qwen38-27b", "ornith_35b", "expert")
    assert prefs.task_specialization == "leader"


def test_blue_team_role_requires_defensive_security_capabilities():
    prefs = routing_preferences_for_role("blue-team")
    assert prefs.preferred_profiles == ("redsage-8b",)
    assert "cybersecurity" in prefs.required_capabilities
    assert "blue-team" in prefs.required_capabilities
    assert prefs.task_specialization == "blue-team"


def test_dfir_role_prefers_imperum():
    prefs = routing_preferences_for_role("dfir")
    assert prefs.preferred_profiles[0] == "imperum-cyber"
    assert "cybersecurity" in prefs.required_capabilities
    assert "dfir" in prefs.required_capabilities
    assert prefs.task_specialization == "dfir"


def test_specialist_runtime_templates_are_disabled_by_default():
    profiles = {profile.name: profile for profile in default_runtime_profiles()}

    for name in ("qwen38-27b", "redsage-8b", "imperum-cyber", "deephat-7b"):
        assert name in profiles
        assert profiles[name].enabled is False

    assert "leader" in profiles["qwen38-27b"].specialization_tags
    assert "blue-team" in profiles["redsage-8b"].capability_tags
    assert "dfir" in profiles["imperum-cyber"].capability_tags
    assert "red-team" in profiles["deephat-7b"].capability_tags
    assert profiles["hexstrike-suite"].enabled is True
    assert "suite:hexstrike" in profiles["hexstrike-suite"].capability_tags
