from __future__ import annotations

import os
from pathlib import Path

from ..config import load_settings, models_dir, repo_root


def voicestudio_base_url() -> str:
    env = (os.environ.get("JARVIS_VOICESTUDIO_URL") or os.environ.get("VOICESTUDIO_URL") or "").strip()
    if env:
        return env.rstrip("/")
    try:
        configured = (load_settings().voice.voicestudio_url or "").strip()
        if configured:
            return configured.rstrip("/")
    except Exception:
        pass
    return "http://127.0.0.1:3900"


def voicestudio_auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {"User-Agent": "Jarvis-TTS/1.0"}
    api_key = (os.environ.get("JARVIS_VOICESTUDIO_API_KEY") or os.environ.get("OMNIVOICE_API_KEY") or "").strip()
    if not api_key:
        try:
            api_key = (load_settings().voice.voicestudio_api_key or "").strip()
        except Exception:
            api_key = ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    pin = (os.environ.get("JARVIS_VOICESTUDIO_PIN") or "").strip()
    if pin:
        headers["X-OmniVoice-Pin"] = pin
    return headers


def whisper_model_dir_marker() -> Path:
    return models_dir() / "whisper" / ".jarvis_faster_whisper_dir"


def resolved_faster_whisper_model() -> str | None:
    """Directory or model id/path for faster-whisper WhisperModel()."""
    try:
        configured = (load_settings().voice.whisper_model or "").strip()
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = repo_root() / configured
            if path.is_dir() or path.is_file():
                return str(path)
            return configured
    except Exception:
        pass

    env = (os.environ.get("JARVIS_WHISPER_MODEL") or "").strip()
    if env:
        path = Path(env).expanduser()
        if path.is_dir() or path.is_file():
            return str(path)
        return env

    marker = whisper_model_dir_marker()
    if marker.is_file():
        text = marker.read_text(encoding="utf-8").strip()
        if text:
            path = Path(text).expanduser()
            if path.is_dir() or path.is_file():
                return text

    base_dir = models_dir() / "whisper" / "base"
    if base_dir.is_dir() and any(base_dir.iterdir()):
        return str(base_dir)

    return None
