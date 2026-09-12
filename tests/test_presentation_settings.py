from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.api import settings as settings_api
from app.config import AppSettings, PresentationSettings


def test_presentation_defaults_are_neural_hud():
    presentation = PresentationSettings()
    assert presentation.shell == "hud"
    assert presentation.requested_presence == "neural"
    assert presentation.performance_preset == "auto"
    assert presentation.attention_mode == "pointer"
    assert presentation.reduced_motion == "system"
    assert presentation.avatar_id == "jarvis_base"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("shell", "desktop"),
        ("requested_presence", "avatar"),
        ("performance_preset", "ultra"),
        ("attention_mode", "always_camera"),
        ("reduced_motion", "disabled"),
        ("avatar_id", "../face-data"),
    ],
)
def test_invalid_presentation_values_are_rejected(field: str, value: str):
    with pytest.raises(ValidationError):
        PresentationSettings.model_validate({field: value})


def test_requested_humanoid_round_trips_without_effective_renderer_state():
    settings = AppSettings(
        presentation={
            "shell": "hud",
            "requested_presence": "humanoid",
            "performance_preset": "cinematic",
            "attention_mode": "camera",
            "reduced_motion": "full",
            "avatar_id": "jarvis_base",
        }
    )

    restored = AppSettings.model_validate(settings.model_dump())
    presentation = restored.presentation.model_dump()
    assert presentation["requested_presence"] == "humanoid"
    assert presentation["attention_mode"] == "camera"
    assert "effective_presence" not in presentation
    assert "camera_frame" not in presentation
    assert "embedding" not in presentation


def test_requested_particle_bust_round_trips_without_effective_renderer_state():
    presentation = PresentationSettings(requested_presence="particle_bust").model_dump()
    assert presentation["requested_presence"] == "particle_bust"


def test_settings_update_validates_presentation_enum_values():
    with pytest.raises(ValidationError):
        settings_api.SettingsUpdate(presentation_requested_presence="unsupported")
    with pytest.raises(ValidationError):
        settings_api.SettingsUpdate(presentation_attention_mode="automatic")


def test_settings_update_persists_requested_presence(monkeypatch):
    current = AppSettings()
    saved: list[AppSettings] = []

    monkeypatch.setattr(settings_api, "load_settings", lambda: current)
    monkeypatch.setattr(settings_api, "save_settings", lambda value: saved.append(value.model_copy(deep=True)))
    monkeypatch.setattr(settings_api.REGISTRY, "apply_settings", lambda _value: None)

    result = asyncio.run(
        settings_api.update_settings(
            settings_api.SettingsUpdate(
                presentation_shell="hud",
                presentation_requested_presence="humanoid",
                presentation_performance_preset="balanced",
                presentation_attention_mode="camera",
                presentation_reduced_motion="reduce",
                presentation_avatar_id="jarvis_base",
            )
        )
    )

    assert result["presentation"]["requested_presence"] == "humanoid"
    assert result["presentation"]["attention_mode"] == "camera"
    assert saved
    assert saved[-1].presentation.requested_presence == "humanoid"
    assert saved[-1].presentation.reduced_motion == "reduce"
