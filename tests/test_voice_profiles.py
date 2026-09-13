from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings, save_settings
from app.main import app
from app.voice_profiles.catalog import (
    DEFAULT_VOICE_PROFILE_ID,
    VoiceProfileCatalog,
    get_active_voice_profile_id,
    reload_catalog,
    set_active_voice_profile_id,
)
from app.voice_profiles.ip_guard import contains_forbidden_ip_term, validate_profile_ip_fields
from app.voice_profiles.schema import VoiceProfile, VoiceProfileTTS


@pytest.fixture
def voice_profiles_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    reload_catalog()
    yield jarvis_env
    reload_catalog()


def _write_profile(tmp_path, profile_id: str, **overrides):
    pack_dir = tmp_path / "voice_packs" / profile_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": profile_id,
        "archetype": "british_butler",
        "display_name": "Household butler (original)",
        "license": "original",
        "provenance": "test",
        "tts": {
            "engine_hint": "system",
            "speaker_ref": "jarvis_butler_v1",
            "pack_path": "",
        },
        "persona_hooks": {"register": "british_understated", "humour": "dry"},
        "sample_utterance": "At your service.",
        "vram_class": "balanced",
        "builtin": True,
    }
    payload.update(overrides)
    (pack_dir / "profile.json").write_text(json.dumps(payload), encoding="utf-8")


def test_catalog_loads_default_butler_profile():
    reload_catalog()
    catalog = reload_catalog()
    profile = catalog.get(DEFAULT_VOICE_PROFILE_ID)
    assert profile is not None
    assert profile.archetype == "british_butler"
    assert profile.display_name == "Household butler (original)"
    assert profile.license == "original"
    assert profile.sample_utterance == "At your service, sir."


def test_catalog_lists_stub_profiles_as_unavailable(monkeypatch):
    monkeypatch.setattr("app.voice_profiles.catalog.pick_engine_for_profile", lambda _profile: "system")
    reload_catalog()
    catalog = reload_catalog()
    items = catalog.list_profiles(DEFAULT_VOICE_PROFILE_ID)
    by_id = {item.id: item for item in items}
    assert by_id[DEFAULT_VOICE_PROFILE_ID].available is True
    stub = by_id["tactical_aide_original_v1"]
    assert stub.available is False
    assert stub.unavailable_reason == "install_required"
    assert stub.install_hint is not None
    assert "install" in stub.install_hint.lower()


def test_active_selection_persists(voice_profiles_env, monkeypatch):
    settings = voice_profiles_env["settings"]
    settings.voice.active_profile_id = DEFAULT_VOICE_PROFILE_ID
    save_settings(settings)
    monkeypatch.setattr("app.voice_profiles.catalog.pick_engine_for_profile", lambda _profile: "system")
    reload_catalog()

    activated = set_active_voice_profile_id(DEFAULT_VOICE_PROFILE_ID)
    assert activated.id == DEFAULT_VOICE_PROFILE_ID
    assert activated.active is True
    assert get_active_voice_profile_id() == DEFAULT_VOICE_PROFILE_ID


def test_forbidden_id_rejection():
    assert contains_forbidden_ip_term("codsworth_clone")
    assert contains_forbidden_ip_term("Cortana Voice")
    with pytest.raises(ValueError, match="forbidden"):
        validate_profile_ip_fields(
            profile_id="ultron_voice_v1",
            display_name="Safe label",
            archetype="synthetic",
        )


def test_set_active_rejects_forbidden_id(voice_profiles_env, monkeypatch):
    monkeypatch.setattr("app.voice_profiles.catalog.pick_engine_for_profile", lambda _profile: "system")
    reload_catalog()
    with pytest.raises(ValueError, match="forbidden"):
        set_active_voice_profile_id("codsworth_voice_v1")


def test_set_active_rejects_unavailable_stub(voice_profiles_env, monkeypatch):
    monkeypatch.setattr("app.voice_profiles.catalog.pick_engine_for_profile", lambda _profile: "system")
    reload_catalog()
    with pytest.raises(PermissionError):
        set_active_voice_profile_id("tactical_aide_original_v1")


def test_api_list_and_set_active(voice_profiles_env, monkeypatch):
    monkeypatch.setattr("app.voice_profiles.catalog.pick_engine_for_profile", lambda _profile: "system")
    reload_catalog()
    client = TestClient(app)

    listed = client.get("/api/voice-profiles")
    assert listed.status_code == 200
    body = listed.json()
    assert body["active_voice_profile_id"] == DEFAULT_VOICE_PROFILE_ID
    assert any(item["id"] == DEFAULT_VOICE_PROFILE_ID for item in body["profiles"])

    forbidden = client.put(
        "/api/voice-profiles/active",
        json={"voice_profile_id": "cortana_style"},
    )
    assert forbidden.status_code == 400

    unavailable = client.put(
        "/api/voice-profiles/active",
        json={"voice_profile_id": "tactical_aide_original_v1"},
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["error"] == "install_required"

    active = client.put(
        "/api/voice-profiles/active",
        json={"voice_profile_id": DEFAULT_VOICE_PROFILE_ID},
    )
    assert active.status_code == 200
    assert active.json()["voice_profile_id"] == DEFAULT_VOICE_PROFILE_ID


def test_api_preview_unavailable_stub_returns_409(voice_profiles_env, monkeypatch):
    monkeypatch.setattr("app.voice_profiles.catalog.pick_engine_for_profile", lambda _profile: "system")
    reload_catalog()
    client = TestClient(app)
    response = client.post("/api/voice-profiles/tactical_aide_original_v1/preview")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_preview_available_profile(voice_profiles_env, monkeypatch):
    from app.api.voice_profiles import preview_voice_profile

    async def fake_synthesize(text: str, *, voice_profile_id: str | None = None) -> bytes:
        assert voice_profile_id == DEFAULT_VOICE_PROFILE_ID
        return b"RIFF"

    monkeypatch.setattr("app.api.voice_profiles.synthesize_speech", fake_synthesize)
    monkeypatch.setattr("app.voice_profiles.catalog.pick_engine_for_profile", lambda _profile: "system")
    reload_catalog()
    response = await preview_voice_profile(DEFAULT_VOICE_PROFILE_ID)
    assert response.body == b"RIFF"
    assert response.media_type == "audio/wav"


def test_catalog_skips_forbidden_pack_on_load(tmp_path, monkeypatch):
    monkeypatch.setattr("app.voice_profiles.catalog.repo_root", lambda: tmp_path)
    forbidden_dir = tmp_path / "voice_packs" / "codsworth_voice_v1"
    forbidden_dir.mkdir(parents=True)
    (forbidden_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "codsworth_voice_v1",
                "archetype": "british_butler",
                "display_name": "Codsworth",
                "license": "original",
                "provenance": "bad",
                "tts": {"engine_hint": "system", "speaker_ref": "", "pack_path": ""},
                "persona_hooks": {"register": "", "humour": ""},
                "sample_utterance": "Hello",
                "vram_class": "balanced",
                "builtin": True,
            }
        ),
        encoding="utf-8",
    )
    catalog = VoiceProfileCatalog()
    assert catalog.get("codsworth_voice_v1") is None


def test_active_voice_profile_id_defaults_when_missing(voice_profiles_env, monkeypatch):
    settings: AppSettings = voice_profiles_env["settings"]
    object.__setattr__(settings.voice, "active_profile_id", "   ")
    monkeypatch.setattr("app.config.load_settings", lambda: settings)
    monkeypatch.setattr("app.voice_profiles.catalog.load_settings", lambda: settings)
    assert get_active_voice_profile_id() == DEFAULT_VOICE_PROFILE_ID
