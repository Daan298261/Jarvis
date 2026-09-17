from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any

from ..config import models_dir, repo_root
from .kokoro_adapter import (
    KOKORO_HF_REPO,
    KOKORO_MODEL_DIR,
    is_kokoro_installable,
    kokoro_assets_ready,
    kokoro_package_ready,
    kokoro_runtime_state,
)

CHATTERBOX_MODEL_DIR = models_dir() / "tts" / "chatterbox-turbo"
PIPER_VOICES_DIR = models_dir() / "tts" / "piper"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def resolve_engine_id(tts: Any | None) -> str:
    if tts is None:
        return "system"
    if hasattr(tts, "engine_id"):
        raw = (getattr(tts, "engine_id", "") or getattr(tts, "engine_hint", "") or "system").strip().lower()
    elif isinstance(tts, dict):
        raw = (tts.get("engine_id") or tts.get("engine_hint") or "system").strip().lower()
    else:
        raw = "system"
    return raw or "system"


def kokoro_weights_ready(model_dir: Path | None = None) -> bool:
    return kokoro_assets_ready(model_dir)


def kokoro_python_ready() -> bool:
    return kokoro_package_ready()


def is_kokoro_available(*, model_dir: Path | None = None) -> bool:
    """Return true only after the bundled Kokoro runtime produced valid audio."""
    del model_dir
    return kokoro_runtime_state().ready


def is_piper_available() -> bool:
    if shutil.which("piper"):
        return True
    return _module_available("piper")


def is_chatterbox_available() -> bool:
    return _module_available("chatterbox")


def legacy_system_tts_available() -> bool:
    import sys

    if sys.platform == "win32":
        return True
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        return True
    return _module_available("pyttsx3")


def is_engine_available(engine_id: str) -> bool:
    key = (engine_id or "system").strip().lower()
    if key in {"kokoro"}:
        return is_kokoro_available()
    if key in {"piper"}:
        return is_piper_available()
    if key in {"chatterbox", "chatterbox-turbo", "chatterbox_turbo"}:
        return is_chatterbox_available()
    if key in {"orpheus", "qwen3-tts", "qwen3_tts"}:
        return False
    if key in {"system", "sapi", "windows", "espeak", "espeak-ng", "pyttsx3"}:
        return legacy_system_tts_available()
    return False


def engine_chain_for_profile(profile: Any) -> list[str]:
    primary = resolve_engine_id(profile.tts)
    if primary == "chatterbox":
        return ["chatterbox", "kokoro"]
    if primary == "kokoro":
        return ["kokoro"]
    if primary == "piper":
        return ["piper"]
    if primary in {"orpheus", "qwen3-tts"}:
        return [primary, "kokoro"]
    return ["system"]


def pick_engine_for_profile(profile: Any) -> str | None:
    for engine in engine_chain_for_profile(profile):
        if is_engine_available(engine):
            return engine
    return None


def primary_tts_backend() -> str | None:
    if is_kokoro_available():
        return "kokoro"
    if is_piper_available():
        return "piper"
    if legacy_system_tts_available():
        import sys

        if sys.platform == "win32":
            return "sapi"
        if shutil.which("espeak-ng"):
            return "espeak-ng"
        if shutil.which("espeak"):
            return "espeak"
        if _module_available("pyttsx3"):
            return "pyttsx3"
        return "sapi"
    return None


def engine_availability() -> dict[str, Any]:
    kokoro_state = kokoro_runtime_state()
    return {
        "kokoro": kokoro_state.ready,
        "kokoro_installable": is_kokoro_installable(),
        "piper": is_piper_available(),
        "chatterbox": is_chatterbox_available(),
        "system": legacy_system_tts_available(),
        "kokoro_weights": kokoro_state.assets_ready,
        "kokoro_model_dir": str(KOKORO_MODEL_DIR),
        "kokoro_runtime": kokoro_state.to_dict(),
        "chatterbox_opt_in": is_chatterbox_available(),
    }


def resolve_pack_model_dir(profile: Any) -> Path:
    pack_path = (profile.tts.pack_path or "").strip()
    if pack_path:
        pack_root = Path(pack_path)
        if not pack_root.is_absolute():
            pack_root = repo_root() / pack_path
        manifest = pack_root / "pack.json"
        if manifest.is_file():
            try:
                import json

                payload = json.loads(manifest.read_text(encoding="utf-8"))
                rel = (payload.get("model_rel_path") or "").strip()
                if rel:
                    path = Path(rel)
                    if not path.is_absolute():
                        path = repo_root() / rel
                    return path
            except Exception:
                pass
    return KOKORO_MODEL_DIR
