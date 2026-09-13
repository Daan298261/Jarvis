from __future__ import annotations

import importlib
import json
import logging
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from huggingface_hub import snapshot_download

from ..config import repo_root
from ..voice_profiles.catalog import reload_catalog, voice_packs_dir
from ..voice_profiles.schema import VoiceProfile
from .engines import (
    KOKORO_HF_REPO,
    KOKORO_MODEL_DIR,
    kokoro_python_ready,
    kokoro_weights_ready,
)

logger = logging.getLogger(__name__)

KOKORO_PY_PACKAGES = ("kokoro>=0.9.2", "soundfile>=0.13.0")
_ENSURE_LOCK = threading.Lock()
KOKORO_RUNTIME_ERROR = (
    "The household voice could not be prepared. Check that this PC is online, then try "
    "Install household voice in Settings, or re-run Jarvis Setup."
)

OPTIONAL_PACK_INSTALL: dict[str, dict[str, Any]] = {
    "butler_original_v1": {
        "engine_id": "kokoro",
        "model_id": "kokoro-82m",
        "speaker_ref": "bm_daniel",
        "model_rel_path": "models/tts/kokoro-82m",
        "quality_tier": "natural",
        "license": "Apache-2.0",
        "speaking_rate": 0.96,
        "download_kokoro": True,
    },
    "tactical_aide_original_v1": {
        "engine_id": "kokoro",
        "model_id": "kokoro-82m",
        "speaker_ref": "af_bella",
        "model_rel_path": "models/tts/kokoro-82m",
        "quality_tier": "natural",
        "license": "Apache-2.0",
        "download_kokoro": True,
    },
    "dry_butler_original_v1": {
        "engine_id": "kokoro",
        "model_id": "kokoro-82m",
        "speaker_ref": "bm_lewis",
        "model_rel_path": "models/tts/kokoro-82m",
        "quality_tier": "natural",
        "license": "Apache-2.0",
        "download_kokoro": True,
    },
    "chatterbox_expressive_en_v1": {
        "engine_id": "chatterbox",
        "model_id": "chatterbox-turbo",
        "speaker_ref": "jarvis_butler_expressive_v1",
        "model_rel_path": "models/tts/chatterbox-turbo",
        "quality_tier": "expressive",
        "license": "MIT",
        "download_kokoro": False,
        "detail": "Enable JARVIS_TTS_CHATTERBOX=1 and stage Chatterbox-Turbo weights under models/tts/chatterbox-turbo.",
    },
    "synthetic_command_original_v1": {
        "engine_id": "kokoro",
        "model_id": "kokoro-82m",
        "speaker_ref": "am_michael",
        "model_rel_path": "models/tts/kokoro-82m",
        "quality_tier": "baseline",
        "license": "Apache-2.0",
        "download_kokoro": True,
    },
}


@dataclass
class VoicePackInstallResult:
    profile_id: str
    ok: bool
    detail: str
    pack_path: str = ""


def _pack_dir(profile: VoiceProfile) -> Path:
    rel = (profile.tts.pack_path or f"voice_packs/{profile.id}").strip()
    path = Path(rel)
    if not path.is_absolute():
        path = repo_root() / rel
    return path


def ensure_kokoro_python(*, force: bool = False) -> None:
    """Install Kokoro into this Jarvis interpreter. End users never run pip themselves."""
    if not force and kokoro_python_ready():
        return
    logger.info("Installing Kokoro TTS packages into %s", sys.executable)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade",
        *KOKORO_PY_PACKAGES,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(KOKORO_RUNTIME_ERROR) from exc
    if completed.returncode != 0:
        logger.error("Kokoro package install failed: %s", (completed.stderr or completed.stdout)[-2000:])
        raise RuntimeError(KOKORO_RUNTIME_ERROR)
    importlib.invalidate_caches()
    if not kokoro_python_ready():
        raise RuntimeError(KOKORO_RUNTIME_ERROR)


def ensure_kokoro_weights(*, force: bool = False) -> Path:
    KOKORO_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not force and kokoro_weights_ready(KOKORO_MODEL_DIR):
        return KOKORO_MODEL_DIR
    logger.info("Downloading Kokoro-82M weights to %s", KOKORO_MODEL_DIR)
    snapshot_download(
        repo_id=KOKORO_HF_REPO,
        local_dir=str(KOKORO_MODEL_DIR),
        local_dir_use_symlinks=False,
    )
    marker = KOKORO_MODEL_DIR / ".jarvis_staged_ok"
    marker.write_text("ok\n", encoding="utf-8")
    return KOKORO_MODEL_DIR


def ensure_kokoro_runtime(*, force: bool = False) -> Path:
    """Make the default household voice usable: Python engine + bundled weights."""
    with _ENSURE_LOCK:
        ensure_kokoro_python(force=force)
        return ensure_kokoro_weights(force=force)


def install_voice_pack(profile: VoiceProfile, *, force: bool = False) -> VoicePackInstallResult:
    spec = OPTIONAL_PACK_INSTALL.get(profile.id)
    if spec is None and not profile.tts.pack_path:
        return VoicePackInstallResult(
            profile_id=profile.id,
            ok=False,
            detail="This profile has no one-click install path.",
        )

    pack_dir = _pack_dir(profile)
    pack_dir.mkdir(parents=True, exist_ok=True)
    merged = dict(spec or {})
    merged.setdefault("pack_id", profile.id)
    merged.setdefault("engine_id", profile.tts.engine_id or profile.tts.engine_hint or "kokoro")
    merged.setdefault("speaker_ref", profile.tts.speaker_ref)
    merged.setdefault("model_rel_path", "models/tts/kokoro-82m")
    merged.setdefault("license", "Apache-2.0")
    merged.setdefault("offline", True)

    if merged.get("download_kokoro"):
        ensure_kokoro_runtime(force=force)

    manifest_path = pack_dir / "pack.json"
    manifest_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    reload_catalog()
    return VoicePackInstallResult(
        profile_id=profile.id,
        ok=True,
        detail=merged.get("detail") or "Voice pack installed.",
        pack_path=str(pack_dir.relative_to(repo_root()) if str(pack_dir).startswith(str(repo_root())) else pack_dir),
    )


def list_installable_profile_ids() -> list[str]:
    root = voice_packs_dir()
    if not root.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(root.glob("*/profile.json")):
        profile_id = path.parent.name
        if profile_id in OPTIONAL_PACK_INSTALL:
            ids.append(profile_id)
    return ids
