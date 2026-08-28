from __future__ import annotations

import pytest

from app.inference.profiles import PROFILES
from app.inference.runtime_profiles import (
    PRIVACY_LOCAL_ONLY,
    PRIVACY_PUBLIC_REMOTE,
    RuntimeProfile,
    create_runtime_profile,
    default_runtime_profiles,
    delete_runtime_profile,
    get_runtime_profile,
    list_runtime_profiles,
    reset_runtime_profiles,
    runtime_profiles_root,
    update_runtime_profile,
)
from app.inference.runtime_router import (
    AgentRoutingPreferences,
    RuntimeNodeState,
    route_runtime,
    score_runtime_candidate,
)


@pytest.fixture
def runtime_store(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    reset_runtime_profiles()
    return jarvis_env["tmp"]


def test_default_runtime_profiles_include_model_fields(runtime_store):
    profiles = list_runtime_profiles()
    assert len(profiles) >= 4
    balanced = get_runtime_profile("balanced")
    assert balanced is not None
    assert balanced.model == "Qwen3.5-9B"
    assert balanced.provider == "local-llama"
    assert balanced.endpoint == "127.0.0.1:8088"
    assert balanced.context_limit == 32768
    assert balanced.quantization == "Q8_0"
    assert balanced.privacy_class == PRIVACY_LOCAL_ONLY
    assert balanced.cost_ceiling_usd == 0.0
    assert "llm_inference" in balanced.capability_tags


def test_default_runtime_profiles_link_model_profiles():
    profiles = default_runtime_profiles()
    by_name = {profile.name: profile for profile in profiles}
    assert set(by_name) == {"fast", "balanced", "quality", "expert"}
    balanced = by_name["balanced"]
    assert isinstance(balanced, RuntimeProfile)
    assert balanced.model_profile == "balanced"
    assert balanced.context_limit == PROFILES["balanced"].context_size
    assert balanced.quantization == PROFILES["balanced"].quant


def test_runtime_profile_crud(runtime_store):
    created = create_runtime_profile(
        name="cloud-fast",
        label="Cloud Fast",
        model="gpt-4o-mini",
        provider="openai-compat",
        endpoint="https://api.example.com/v1",
        context_limit=8192,
        quantization="fp16",
        privacy_class=PRIVACY_PUBLIC_REMOTE,
        cost_ceiling_usd=0.001,
        capability_tags=["llm_inference", "text"],
        specialization_tags=["low-latency"],
        is_local=False,
        description="Cheap remote endpoint",
    )
    assert created.name == "cloud-fast"
    assert get_runtime_profile(created.id) is not None

    updated = update_runtime_profile(created.id, label="Cloud Fast v2", context_limit=16384)
    assert updated.label == "Cloud Fast v2"
    assert updated.context_limit == 16384

    delete_runtime_profile(created.id)
    assert get_runtime_profile(created.id) is None


def test_route_prefers_preferred_profile(runtime_store):
    prefs = AgentRoutingPreferences(
        preferred_profiles=("quality",),
        policy="best-result",
    )
    decision = route_runtime(prefs)
    assert decision.accepted is True
    assert decision.runtime_profile is not None
    assert decision.runtime_profile.name == "quality"
    assert decision.score is not None
    assert decision.score.preferred_bonus > 0
    assert decision.reason


def test_route_respects_forbidden_profiles(runtime_store):
    prefs = AgentRoutingPreferences(
        forbidden_profiles=("fast", "balanced", "quality", "expert"),
        policy="best-result",
    )
    decision = route_runtime(prefs)
    assert decision.accepted is False
    assert decision.code == "no_profile"


def test_route_force_profile_overrides_preference(runtime_store):
    prefs = AgentRoutingPreferences(
        preferred_profiles=("quality",),
        force_profile="fast",
        policy="best-result",
    )
    decision = route_runtime(prefs)
    assert decision.accepted is True
    assert decision.runtime_profile is not None
    assert decision.runtime_profile.name == "fast"


def test_route_force_forbidden_fails_closed(runtime_store):
    prefs = AgentRoutingPreferences(
        force_profile="fast",
        forbidden_profiles=("fast",),
        policy="best-result",
    )
    decision = route_runtime(prefs)
    assert decision.accepted is False
    assert decision.code == "forced_forbidden"


def test_route_local_only_policy(runtime_store):
    create_runtime_profile(
        name="remote-only",
        model="remote-model",
        provider="openai-compat",
        endpoint="https://api.example.com/v1",
        privacy_class=PRIVACY_PUBLIC_REMOTE,
        is_local=False,
    )
    prefs = AgentRoutingPreferences(policy="local-only")
    decision = route_runtime(prefs)
    assert decision.accepted is True
    assert decision.runtime_profile is not None
    assert decision.runtime_profile.is_local is True


def test_route_local_only_fails_without_local_profiles(runtime_store):
    profiles = [
        RuntimeProfile(
            id="remote-1",
            name="remote-only",
            label="Remote",
            model="remote-model",
            provider="openai-compat",
            endpoint="https://api.example.com/v1",
            context_limit=8192,
            quantization="fp16",
            privacy_class=PRIVACY_PUBLIC_REMOTE,
            cost_ceiling_usd=0.002,
            capability_tags=("llm_inference",),
            is_local=False,
        )
    ]
    prefs = AgentRoutingPreferences(policy="local-only")
    decision = route_runtime(prefs, profiles=profiles)
    assert decision.accepted is False
    assert decision.code == "no_local_profile"


def test_route_privacy_fails_closed_for_remote(runtime_store):
    profiles = [
        RuntimeProfile(
            id="remote-1",
            name="remote-only",
            label="Remote",
            model="remote-model",
            provider="openai-compat",
            endpoint="https://api.example.com/v1",
            context_limit=8192,
            quantization="fp16",
            privacy_class=PRIVACY_PUBLIC_REMOTE,
            cost_ceiling_usd=0.002,
            capability_tags=("llm_inference",),
            is_local=False,
        )
    ]
    prefs = AgentRoutingPreferences(policy="best-result", privacy_floor=PRIVACY_LOCAL_ONLY)
    decision = route_runtime(prefs, profiles=profiles)
    assert decision.accepted is False
    assert decision.code == "privacy_forbidden"


def test_route_warm_model_bonus(runtime_store):
    prefs = AgentRoutingPreferences(policy="best-result")
    balanced = get_runtime_profile("balanced")
    assert balanced is not None
    cold = score_runtime_candidate(
        balanced,
        RuntimeNodeState(node_id="localhost", warm_models=()),
        prefs,
        policy="best-result",
    )
    warm = score_runtime_candidate(
        balanced,
        RuntimeNodeState(node_id="localhost", warm_models=("balanced",)),
        prefs,
        policy="best-result",
    )
    assert warm.warm_bonus > cold.warm_bonus
    assert warm.total > cold.total


def test_route_specialization_bonus(runtime_store):
    prefs = AgentRoutingPreferences(policy="best-result", task_specialization="reasoning")
    quality = get_runtime_profile("quality")
    fast = get_runtime_profile("fast")
    assert quality is not None and fast is not None
    quality_score = score_runtime_candidate(
        quality,
        RuntimeNodeState(node_id="localhost"),
        prefs,
        policy="best-result",
    )
    fast_score = score_runtime_candidate(
        fast,
        RuntimeNodeState(node_id="localhost"),
        prefs,
        policy="best-result",
    )
    assert quality_score.specialization_bonus > fast_score.specialization_bonus


def test_route_cost_optimized_prefers_local(runtime_store):
    create_runtime_profile(
        name="expensive-remote",
        model="gpt-4",
        provider="openai-compat",
        endpoint="https://api.example.com/v1",
        privacy_class=PRIVACY_PUBLIC_REMOTE,
        cost_ceiling_usd=0.05,
        is_local=False,
    )
    prefs = AgentRoutingPreferences(policy="cost-optimized")
    decision = route_runtime(prefs)
    assert decision.accepted is True
    assert decision.runtime_profile is not None
    assert decision.runtime_profile.is_local is True


def test_route_emits_explainable_score(runtime_store):
    prefs = AgentRoutingPreferences(policy="local-first", preferred_profiles=("balanced",))
    decision = route_runtime(prefs)
    assert decision.accepted is True
    assert decision.score is not None
    assert decision.score.total > 0
    assert decision.score.reasons
    assert decision.node is not None
    assert decision.node.node_id == "localhost"


def test_route_required_capabilities_filter(runtime_store):
    prefs = AgentRoutingPreferences(
        policy="best-result",
        required_capabilities=("vision",),
    )
    decision = route_runtime(prefs)
    assert decision.accepted is False
    assert decision.code == "no_profile"


def test_runtime_registry_persists(runtime_store):
    created = create_runtime_profile(
        name="persisted",
        model="m",
        endpoint="http://127.0.0.1:9000/v1",
    )
    path = runtime_profiles_root() / "registry.json"
    assert path.exists()
    loaded = list_runtime_profiles()
    assert any(item.id == created.id for item in loaded)


def test_runtime_profiles_api(runtime_store, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: runtime_store)
    client = TestClient(app)

    listed = client.get("/api/runtime-profiles")
    assert listed.status_code == 200
    assert len(listed.json()["profiles"]) >= 4
    assert "local-first" in listed.json()["policies"]

    created = client.post(
        "/api/runtime-profiles",
        json={
            "name": "api-remote",
            "model": "gpt-4o-mini",
            "endpoint": "https://api.example.com/v1",
            "is_local": False,
        },
    )
    assert created.status_code == 200
    profile_id = created.json()["id"]

    routed = client.post(
        "/api/runtime-profiles/route/preview",
        json={"preferred_profiles": ["balanced"], "policy": "local-first"},
    )
    assert routed.status_code == 200
    assert routed.json()["accepted"] is True
    assert routed.json()["runtime_profile"]["name"] == "balanced"

    deleted = client.delete(f"/api/runtime-profiles/{profile_id}")
    assert deleted.status_code == 200
