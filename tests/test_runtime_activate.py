from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.inference.backends import resolve_advertised_model
from app.inference.hotswap import apply_runtime_profile_to_settings, local_lmstudio_fallback_settings
from app.inference.runtime_profiles import create_runtime_profile
from app import main as main_module
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

    runtime = create_runtime_profile(
        name="lm-probe-test-unique",
        label="Probe test",
        model="catalog-stem",
        provider="lmstudio",
        endpoint="127.0.0.1:1234",
        context_limit=8192,
        is_local=True,
    )
    saved = []
    monkeypatch.setattr("app.inference.hotswap.save_settings", lambda value: saved.append(value))
    await apply_runtime_profile_to_settings(runtime)

    assert settings.inference.backend == "llama.cpp"
    assert len(saved) == 1
    assert saved[0].inference.backend == "lmstudio"
    assert saved[0].inference.host == "127.0.0.1"
    assert saved[0].inference.port == 1234
    assert saved[0].inference.remote_model == "my-loaded-model"


@pytest.mark.asyncio
async def test_unreachable_lmstudio_profile_does_not_save_or_mutate_current_settings(jarvis_env, monkeypatch):
    settings = jarvis_env["settings"]
    settings.inference.backend = "llama.cpp"
    settings.inference.port = 8088
    saved = []

    async def unavailable(*_args, **_kwargs):
        return {"ok": False, "error": "connection refused", "models": []}

    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.inference.hotswap.probe_remote_server", unavailable)
    monkeypatch.setattr("app.inference.hotswap.load_settings", lambda: settings)
    monkeypatch.setattr("app.inference.hotswap.save_settings", lambda value: saved.append(value))
    runtime = create_runtime_profile(
        name="lm-unavailable-test",
        model="catalog-stem",
        provider="lmstudio",
        endpoint="127.0.0.1:1234",
        is_local=True,
    )

    with pytest.raises(RuntimeError, match="Could not reach lmstudio"):
        await apply_runtime_profile_to_settings(runtime)

    assert settings.inference.backend == "llama.cpp"
    assert settings.inference.port == 8088
    assert saved == []


def test_local_lmstudio_fallback_is_limited_to_loopback_and_uses_managed_runtime(jarvis_env):
    settings = jarvis_env["settings"]
    settings.inference.backend = "lmstudio"
    settings.inference.host = "127.0.0.1"
    settings.inference.port = 1234
    settings.inference.remote_model = "stale-lmstudio-model"
    settings.inference.profile = "quality"

    fallback = local_lmstudio_fallback_settings(settings)

    assert fallback is not None
    assert fallback.inference.backend == "llama.cpp"
    assert fallback.inference.host == "127.0.0.1"
    assert fallback.inference.port == 8088
    assert fallback.inference.remote_model == ""
    assert fallback.inference.profile == "quality"
    assert settings.inference.backend == "lmstudio"

    settings.inference.host = "192.168.1.50"
    assert local_lmstudio_fallback_settings(settings) is None


@pytest.mark.asyncio
async def test_autoload_recovers_from_unavailable_local_lmstudio(jarvis_env, monkeypatch):
    settings = jarvis_env["settings"]
    settings.inference.backend = "lmstudio"
    settings.inference.host = "127.0.0.1"
    settings.inference.port = 1234
    settings.inference.profile = "quality"
    calls = []
    saved = []

    async def fake_load(candidate, profile):
        calls.append((candidate.inference.backend, profile))
        if candidate.inference.backend == "lmstudio":
            raise RuntimeError("LM Studio is closed")
        return jarvis_env["manager"].state

    monkeypatch.setattr(main_module.MANAGER, "load", fake_load)
    monkeypatch.setattr(main_module, "preferred_startup_profile", lambda profile: profile)
    monkeypatch.setattr(main_module, "save_settings", lambda value: saved.append(value))

    await main_module._autoload_model(settings)

    assert calls == [("lmstudio", "quality"), ("llama.cpp", "quality")]
    assert len(saved) == 1
    assert saved[0].inference.backend == "llama.cpp"
    assert saved[0].inference.port == 8088


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
