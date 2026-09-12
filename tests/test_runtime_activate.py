from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.inference.backends import resolve_advertised_model
from app.inference.hotswap import apply_runtime_profile_to_settings
from app.inference.runtime_profiles import create_runtime_profile
from app.main import app


def test_resolve_advertised_model_single_listing():
    assert resolve_advertised_model("qwen-stem", ["lmstudio-model-id"]) == "lmstudio-model-id"


def test_resolve_advertised_model_stem_match():
    advertised = ["Qwen3.5-9B-Defiant-Q4_K_M"]
    assert resolve_advertised_model("Qwen3.5-9B-Defiant-Q4", advertised) == advertised[0]


@pytest.mark.asyncio
async def test_apply_runtime_profile_probes_lmstudio_and_sets_remote_model(jarvis_env, monkeypatch):
    settings = jarvis_env["settings"]

    async def fake_probe(host, port, api_key="", timeout=8.0, retry=False):
        assert host == "127.0.0.1"
        assert port == 1234
        return {"ok": True, "health_path": "/v1/models", "models": ["my-loaded-model"]}

    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.inference.hotswap.probe_remote_server", fake_probe)
    monkeypatch.setattr("app.inference.hotswap.load_settings", lambda: settings)
    monkeypatch.setattr("app.inference.hotswap.save_settings", lambda _settings: None)

    runtime = create_runtime_profile(
        name="lm-probe-test-unique",
        label="Probe test",
        model="catalog-stem",
        provider="lmstudio",
        endpoint="127.0.0.1:1234",
        context_limit=8192,
        is_local=True,
    )
    await apply_runtime_profile_to_settings(runtime)

    assert settings.inference.backend == "lmstudio"
    assert settings.inference.host == "127.0.0.1"
    assert settings.inference.port == 1234
    assert settings.inference.remote_model == "my-loaded-model"


@pytest.mark.asyncio
async def test_activate_runtime_profile_endpoint(jarvis_env, monkeypatch):
    settings = jarvis_env["settings"]
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])

    profile = create_runtime_profile(
        name="lm-activate-test",
        label="Activate test",
        model="stem-model",
        provider="lmstudio",
        endpoint="127.0.0.1:1234",
        context_limit=16384,
        is_local=True,
    )

    async def fake_activate(runtime, *, force=True):
        del runtime, force
        from app.inference.manager import MANAGER

        settings.inference.backend = "lmstudio"
        settings.inference.remote_model = "loaded-id"
        MANAGER.state.loaded = True
        return MANAGER.state

    monkeypatch.setattr("app.api.runtime_profiles.activate_runtime_profile", fake_activate)
    monkeypatch.setattr("app.api.runtime_profiles.load_settings", lambda: settings)

    client = TestClient(app)
    response = client.post(f"/api/runtime-profiles/{profile.id}/activate")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["profile"]["id"] == profile.id
    assert body["load"]["loaded"] is True
