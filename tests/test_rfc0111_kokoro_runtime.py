from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from app.tts.engines import kokoro_weights_ready
from app.tts.kokoro_adapter import KokoroAdapter
from app.tts.runtime_state import TtsRuntimeState


def _stage_runtime(root: Path, *voices: str) -> None:
    (root / "voices").mkdir(parents=True)
    (root / "config.json").write_text("{}", encoding="utf-8")
    (root / "kokoro-v1_0.pth").write_bytes(b"weights")
    for voice in voices or ("bm_george",):
        (root / "voices" / f"{voice}.pt").write_bytes(b"voice")


def _install_fake_kokoro(monkeypatch, observed: dict[str, object], *, samples: int = 1600) -> None:
    class FakeModel:
        def __init__(self, **kwargs):
            observed["model_kwargs"] = kwargs

        def eval(self):
            return self

    class FakePipeline:
        def __init__(self, **kwargs):
            observed["pipeline_kwargs"] = kwargs

        def __call__(self, text, *, voice, speed):
            observed["synthesis"] = {"text": text, "voice": voice, "speed": speed}
            yield text, "phonemes", np.ones(samples, dtype=np.float32) * 0.1

    fake_kokoro = ModuleType("kokoro")
    fake_kokoro.KModel = FakeModel
    fake_kokoro.KPipeline = FakePipeline
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)
    monkeypatch.setattr("app.tts.kokoro_adapter.kokoro_package_ready", lambda: True)


def test_runtime_state_ready_requires_all_four_health_gates():
    state = TtsRuntimeState("kokoro", True, True, True, False)
    assert state.ready is False
    assert TtsRuntimeState("kokoro", True, True, True, True).ready is True


def test_is_kokoro_available_is_exactly_verified_runtime_ready(monkeypatch):
    from app.tts import engines

    monkeypatch.setattr(
        engines,
        "kokoro_runtime_state",
        lambda: TtsRuntimeState("kokoro", True, True, True, False),
    )
    assert engines.is_kokoro_available() is False
    monkeypatch.setattr(
        engines,
        "kokoro_runtime_state",
        lambda: TtsRuntimeState("kokoro", True, True, True, True),
    )
    assert engines.is_kokoro_available() is True


def test_kokoro_runtime_requires_model_and_probe_voice(tmp_path):
    assert kokoro_weights_ready(tmp_path) is False
    (tmp_path / ".jarvis_staged_ok").write_text("ok", encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "kokoro-v1_0.pth").write_bytes(b"weights")
    assert kokoro_weights_ready(tmp_path) is False
    (tmp_path / "voices").mkdir()
    (tmp_path / "voices" / "bm_george.pt").write_bytes(b"voice")
    assert kokoro_weights_ready(tmp_path) is True


def test_adapter_constructs_model_and_voice_from_bundled_files(monkeypatch, tmp_path):
    _stage_runtime(tmp_path, "bm_george")
    observed: dict[str, object] = {}
    _install_fake_kokoro(monkeypatch, observed)
    adapter = KokoroAdapter(tmp_path)

    state = adapter.verify()

    assert state.ready is True
    assert observed["model_kwargs"] == {
        "repo_id": "hexgrad/Kokoro-82M",
        "config": str(tmp_path / "config.json"),
        "model": str(tmp_path / "kokoro-v1_0.pth"),
    }
    pipeline_kwargs = observed["pipeline_kwargs"]
    assert pipeline_kwargs["lang_code"] == "b"
    assert pipeline_kwargs["repo_id"] == "hexgrad/Kokoro-82M"
    synthesis = observed["synthesis"]
    assert synthesis["voice"] == str((tmp_path / "voices" / "bm_george.pt").resolve())


def test_adapter_does_not_report_ready_for_empty_audio(monkeypatch, tmp_path):
    _stage_runtime(tmp_path, "bm_george")
    observed: dict[str, object] = {}
    _install_fake_kokoro(monkeypatch, observed, samples=0)
    state = KokoroAdapter(tmp_path).verify()
    assert state.ready is False
    assert state.synthesis_verified is False
    assert "no audio" in state.last_error.lower()


def test_normal_synthesis_never_installs_or_self_verifies(monkeypatch, tmp_path):
    _stage_runtime(tmp_path, "bm_george")
    observed: dict[str, object] = {}
    _install_fake_kokoro(monkeypatch, observed)
    adapter = KokoroAdapter(tmp_path)

    with pytest.raises(RuntimeError, match="health probe"):
        adapter.synthesize("Hello", voice="bm_george", speed=1.0)
    assert "synthesis" not in observed


def test_missing_speaker_is_an_actionable_runtime_failure(monkeypatch, tmp_path):
    _stage_runtime(tmp_path, "bm_george")
    observed: dict[str, object] = {}
    _install_fake_kokoro(monkeypatch, observed)
    adapter = KokoroAdapter(tmp_path)
    assert adapter.verify().ready is True
    with pytest.raises(FileNotFoundError, match="Repair the household voice"):
        adapter.synthesize("Hello", voice="bm_daniel", speed=1.0)


def test_voice_status_reports_requested_and_actual_engine(monkeypatch):
    from app.workers import voice
    from app.voice_profiles import catalog

    state = TtsRuntimeState(
        "kokoro",
        True,
        True,
        True,
        True,
        model_id="kokoro-82m",
        speaker_ref="bm_george",
        device="cpu",
    )
    monkeypatch.setattr(voice, "kokoro_runtime_state", lambda: state)
    monkeypatch.setattr(voice, "stt_backend", lambda: "windows-sapi")
    monkeypatch.setattr(voice, "local_whisper_model", lambda: None)
    monkeypatch.setattr(voice, "_find_ffmpeg", lambda: None)
    monkeypatch.setattr(catalog, "get_active_voice_profile_id", lambda: "butler_original_v1")

    status = voice.voice_status()

    assert status["tts_ready"] is True
    assert status["tts_runtime"]["requested_engine"] == "kokoro"
    assert status["tts_runtime"]["actual_engine"] == "kokoro"
    assert status["tts_runtime"]["fallback_active"] is False
    assert status["tts_runtime"]["ready"] is True
