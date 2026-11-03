from types import SimpleNamespace
import ctypes
import sys

import pytest


def worker():
    from app.api.voice import get_voice_status  # prime the existing import graph
    from app.workers import voice
    return voice


def test_cuda_probe_rejects_missing_dependency(monkeypatch):
    voice = worker()
    def missing(_):
        raise OSError("missing cublas64_12.dll")
    monkeypatch.setattr(ctypes, "WinDLL", missing, raising=False)
    assert not voice._windows_whisper_cuda_ready()


def test_cuda_probe_loads_all_dependencies_and_retains_handles(monkeypatch):
    voice = worker()
    loaded = []
    def load(path):
        loaded.append(path)
        return object()
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    assert voice._windows_whisper_cuda_ready()
    assert len(voice._windows_whisper_cuda_ready.handles) == 3
    assert all(any(name in path for path in loaded) for name in ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll"))


@pytest.mark.parametrize("cuda_ready", [False, True])
def test_windows_transcription_uses_cpu_when_cuda_dependencies_are_missing(monkeypatch, tmp_path, cuda_ready):
    voice = worker()
    calls = []
    def model(name, **options):
        calls.append(options)
        return SimpleNamespace(transcribe=lambda path: (iter([SimpleNamespace(text=" voice works ")]), None))
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(voice, "_windows_whisper_cuda_ready", lambda: cuda_ready)
    assert voice._transcribe_faster_whisper(tmp_path / "speech.wav", "cached-model") == "voice works"
    expected = {"local_files_only": True}
    if not cuda_ready:
        expected.update(device="cpu", compute_type="int8")
    assert calls == [expected]
