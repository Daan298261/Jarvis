"""RFC-0137 named persona catalog. Stubbed packs — no live TTS."""

from __future__ import annotations

import io
import json
import math
import struct
import wave
from pathlib import Path

import pytest

from app.config import AppSettings
from app.persona.named_persona import (
    NamedPersonaBindError,
    ROSTER,
    ROSTER_IDS,
    apply_main_persona,
    attach_specialist,
    card_sentence,
    public_state,
    reapply_stored_main_persona,
    update_appearance,
)
from app.persona.session_personality import maybe_switch_from_owner_message, set_active_mode

NEURAL = {
    "butler_original_v1",
    "chatterbox_expressive_en_v1",
    "dry_butler_original_v1",
    "tactical_aide_original_v1",
    "synthetic_command_original_v1",
}
SAPI = "windows_natural_en_v1"
LOCKED = "Anzu is coordinating. Enki is coding. Themis is verifying security."


@pytest.fixture
def persona_box(monkeypatch):
    box = {"settings": AppSettings()}
    calls: list[str] = []
    available = set(NEURAL)

    monkeypatch.setattr("app.persona.named_persona.load_settings", lambda: box["settings"])
    monkeypatch.setattr("app.persona.named_persona.save_settings", lambda updated: box.__setitem__("settings", updated))
    monkeypatch.setattr("app.persona.session_personality.load_settings", lambda: box["settings"])
    monkeypatch.setattr("app.persona.session_personality.save_settings", lambda updated: box.__setitem__("settings", updated))

    def fake_set(profile_id: str):
        if profile_id == SAPI:
            raise AssertionError("SAPI voice was activated for a named persona")
        calls.append(profile_id)
        box["settings"].voice.active_profile_id = profile_id
        return type("Item", (), {"id": profile_id})()

    def status(profile_id: str) -> str:
        if profile_id == SAPI:
            return "tts_unavailable"
        if profile_id in available:
            return "ok"
        return "tts_unavailable"

    monkeypatch.setattr("app.persona.named_persona.set_active_voice_profile_id", fake_set)
    monkeypatch.setattr("app.voice_profiles.catalog.set_active_voice_profile_id", fake_set)
    monkeypatch.setattr("app.persona.named_persona.pack_status", status)
    return box, calls, available


def test_catalog_is_the_thirteen_roster(persona_box):
    state = public_state()
    assert [row["id"] for row in state["personas"]] == list(ROSTER_IDS)
    assert "eagir" not in [row["id"] for row in state["personas"]]
    assert state["active"]["id"] == "anzu"
    assert state["active"]["presence_shape_id"] == "stormbird"
    shapes = {row["presence_shape_id"] for row in state["personas"]}
    assert "abzu_flow" not in shapes
    assert "root_coil" not in shapes


def test_fresh_install_binds_anzu_butler(persona_box):
    _box, calls, _available = persona_box
    reapply_stored_main_persona()
    active = public_state()["active"]
    assert calls == ["butler_original_v1"]
    assert active["id"] == "anzu"
    assert active["presence_shape_id"] == "stormbird"
    assert active["voice_profile_id"] == "butler_original_v1"
    assert active["voice_profile_requested"] is None


def test_each_persona_binds_its_shape_and_voice(persona_box):
    _box, calls, _available = persona_box
    for row in ROSTER:
        apply_main_persona(row.id)
        active = public_state()["active"]
        assert active["id"] == row.id
        assert active["presence_shape_id"] == row.presence_shape_id
        assert calls[-1] == row.voice_profile_id
        assert calls[-1] != SAPI


def test_anzu_dry_fallback_reports_the_pack_actually_set(persona_box):
    _box, calls, available = persona_box
    available.clear()
    available.add("dry_butler_original_v1")
    apply_main_persona("anzu")
    active = public_state()["active"]
    assert calls == ["dry_butler_original_v1"]
    assert active["voice_profile_id"] == "dry_butler_original_v1"
    assert active["voice_profile_requested"] == "butler_original_v1"
    assert active["presence_shape_id"] == "stormbird"


def test_missing_non_anzu_pack_does_not_write_sapi(persona_box):
    _box, calls, available = persona_box
    apply_main_persona("anzu")
    calls.clear()
    available.discard("tactical_aide_original_v1")
    with pytest.raises(NamedPersonaBindError) as caught:
        apply_main_persona("mestor")
    assert caught.value.code in {"install_required", "tts_unavailable"}
    assert calls == []
    assert SAPI not in calls
    active = public_state()["active"]
    assert active["id"] == "anzu"
    assert active["voice_profile_id"] == "butler_original_v1"


def test_session_mode_does_not_change_shape_or_voice(persona_box):
    _box, calls, _available = persona_box
    apply_main_persona("aegir")
    calls.clear()
    set_active_mode("coding")
    maybe_switch_from_owner_message("switch to research mode")
    set_active_mode("concise")
    assert calls == []
    active = public_state()["active"]
    assert active["id"] == "aegir"
    assert active["presence_shape_id"] == "ocean_swell"
    assert active["voice_profile_id"] == "chatterbox_expressive_en_v1"


def test_migration_eagir_abzu_flow_and_root_coil(persona_box):
    box, _calls, _available = persona_box
    box["settings"].named_personas.active_id = "eagir"
    box["settings"].named_personas.presence_shape_id = "abzu_flow"
    state = public_state()
    assert state["active"]["id"] == "aegir"
    assert "eagir" not in [row["id"] for row in state["personas"]]
    assert box["settings"].named_personas.active_id == "aegir"
    assert box["settings"].named_personas.presence_shape_id == "code_cube"
    assert state["active"]["presence_shape_id"] == "ocean_swell"
    assert all(row["presence_shape_id"] not in {"abzu_flow", "root_coil"} for row in state["personas"])

    box["settings"].named_personas.active_id = "veles"
    box["settings"].named_personas.presence_shape_id = "root_coil"
    state = public_state()
    assert box["settings"].named_personas.presence_shape_id == "serpent_orbit"
    assert state["active"]["id"] == "veles"
    assert state["active"]["presence_shape_id"] == "serpent_orbit"


def test_aegir_alias_and_eagir_store_as_aegir(persona_box):
    _box, calls, _available = persona_box
    apply_main_persona("ægir")
    assert public_state()["active"]["id"] == "aegir"
    assert calls[-1] == "chatterbox_expressive_en_v1"
    apply_main_persona("eagir")
    assert public_state()["active"]["id"] == "aegir"
    with pytest.raises(NamedPersonaBindError):
        apply_main_persona("not-a-persona")


def test_card_sentence_locked_example():
    assert card_sentence("anzu", ["enki", "themis"]) == LOCKED
    assert card_sentence("anzu", ["themis", "enki"]) == LOCKED
    assert card_sentence("enki", ["themis"]) == "Enki is coding. Themis is verifying security."
    assert card_sentence("enki", ["anzu", "themis"]) == (
        "Enki is coordinating. Anzu is coordinating. Themis is verifying security."
    )


def test_appearance_overrides_persist_and_reject_sapi(persona_box):
    _box, calls, _available = persona_box
    apply_main_persona("veles")
    calls.clear()
    update_appearance(
        "veles",
        {
            "pitch": -4,
            "speaking_rate": 0.9,
            "volume": 0.8,
            "orb_color": "#112233",
            "accent_color": "#abcdef",
            "glow": 0.4,
            "animation": 0.2,
            "scale": 1.1,
            "specialists_auto_speak": False,
        },
    )
    assert calls == []
    apply_main_persona("enki")
    apply_main_persona("veles")
    appearance = public_state()["active"]["appearance"]
    assert appearance["pitch"] == -4
    assert appearance["speaking_rate"] == 0.9
    assert appearance["orb_color"] == "#112233"
    assert appearance["specialists_auto_speak"] is False
    with pytest.raises(NamedPersonaBindError):
        update_appearance("veles", {"voice_profile_id": SAPI})
    assert SAPI not in calls
    assert public_state()["active"]["voice_profile_id"] == "synthetic_command_original_v1"


async def test_specialist_attach_keeps_main_shape_and_sentence(persona_box, jarvis_env):
    del jarvis_env
    _box, calls, _available = persona_box
    from app.db.models import Task
    from app.db.session import SessionLocal

    apply_main_persona("anzu")
    async with SessionLocal() as session:
        session.add(Task(id="task-0137", title="Verify", prompt="check the card"))
        await session.commit()
    calls.clear()
    await attach_specialist("enki", "task-0137")
    result = await attach_specialist("themis", "task-0137")
    assert result["card_sentence"] == LOCKED
    assert result["active"]["presence_shape_id"] == "stormbird"
    assert result["active"]["id"] == "anzu"
    assert calls == []
    async with SessionLocal() as session:
        task = await session.get(Task, "task-0137")
        assert task is not None
        ids = json.loads(task.specialist_persona_ids)
    assert ids == ["enki", "themis"]
    assert card_sentence("anzu", ids) == LOCKED


def _wav_peak(wav: bytes) -> int:
    with wave.open(io.BytesIO(wav), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
    return max(abs(sample) for sample in samples)


def test_neural_pcm_rate_and_volume_skip_sapi():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(index / 7.0)))
            for index in range(1600)
        )
        handle.writeframes(frames)
    wav = buffer.getvalue()
    from app.tts.synthesize import apply_neural_pcm_adjustments

    faster = apply_neural_pcm_adjustments(wav, speaking_rate=2.0, volume=0.5, pitch_semitones=0)
    assert len(faster) < len(wav)
    assert _wav_peak(faster) < _wav_peak(wav)
    source = (Path(__file__).resolve().parents[1] / "backend/app/tts/synthesize.py").read_text(encoding="utf-8")
    body = source.split("def apply_neural_pcm_adjustments", 1)[1].split("async def synthesize_with_engine", 1)[0]
    assert "speak_sapi" not in body


def test_named_persona_route_is_registered():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/named-personas" in paths
