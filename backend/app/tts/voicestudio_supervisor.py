"""Start VoiceStudio local API (:3900) when the owner enabled it in settings."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..config import data_dir, load_settings, repo_root, save_settings
from .voice_runtime_config import voicestudio_auth_headers, voicestudio_base_url
from .voicestudio_adapter import voicestudio_probe_endpoint

_log = logging.getLogger(__name__)

_CONTAINER_NAME = "jarvis-voicestudio"
_supervisor_lock = threading.Lock()
_last_start_attempt = 0.0


def _voicestudio_wanted() -> bool:
    try:
        settings = load_settings()
    except Exception:
        return False
    voice = settings.voice
    if voice.voicestudio_autostart:
        return True
    stt = (voice.stt_backend or "auto").strip().lower()
    if stt in {"voicestudio", "voice_studio"}:
        return True
    tts_engine = (settings.tts.engine or "auto").strip().lower()
    if tts_engine in {"voicestudio", "voice_studio"}:
        return True
    try:
        from ..voice_profiles.catalog import get_active_voice_profile

        profile = get_active_voice_profile()
        if profile is not None:
            engine = profile.tts.resolved_engine_id()
            if engine in {"voicestudio", "voice_studio", "omni_voice", "omnivoice"}:
                return True
    except Exception:
        pass
    return False


def _ensure_api_key() -> str:
    settings = load_settings()
    key = (settings.voice.voicestudio_api_key or "").strip()
    if key:
        return key
    key = (os.environ.get("JARVIS_VOICESTUDIO_API_KEY") or os.environ.get("OMNIVOICE_API_KEY") or "").strip()
    if key:
        return key
    import secrets

    key = secrets.token_urlsafe(32)
    settings.voice.voicestudio_api_key = key
    save_settings(settings)
    return key


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _docker_container_running(name: str) -> bool:
    if not _docker_available():
        return False
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return proc.returncode == 0 and proc.stdout.strip().lower() == "true"
    except Exception:
        return False


def _start_docker_voicestudio() -> bool:
    if not _docker_available():
        _log.info("VoiceStudio autostart skipped: docker not on PATH")
        return False
    api_key = _ensure_api_key()
    if _docker_container_running(_CONTAINER_NAME):
        return voicestudio_probe_endpoint(timeout=3.0)
    if subprocess.run(["docker", "inspect", _CONTAINER_NAME], capture_output=True).returncode == 0:
        subprocess.run(["docker", "start", _CONTAINER_NAME], capture_output=True, timeout=120, check=False)
        for _ in range(30):
            if voicestudio_probe_endpoint(timeout=2.0):
                return True
            time.sleep(2)
        return False

    data_volume = data_dir() / "voicestudio"
    data_volume.mkdir(parents=True, exist_ok=True)
    hf_cache = Path.home() / ".cache" / "huggingface"
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        _CONTAINER_NAME,
        "-p",
        "127.0.0.1:3900:3900",
        "-e",
        f"OMNIVOICE_API_KEY={api_key}",
        "-e",
        "OMNIVOICE_SERVER_MODE=1",
        "-v",
        f"{data_volume}:/app/omnivoice_data",
    ]
    if hf_cache.is_dir():
        args.extend(["-v", f"{hf_cache}:/root/.cache/huggingface"])
    args.append("ghcr.io/debpalash/voicestudio:stable")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0:
            _log.warning("VoiceStudio docker run failed: %s", (proc.stderr or proc.stdout).strip())
            return False
    except Exception as exc:
        _log.warning("VoiceStudio docker run error: %s", exc)
        return False
    for _ in range(45):
        if voicestudio_probe_endpoint(timeout=2.0):
            _log.info("VoiceStudio API ready at %s", voicestudio_base_url())
            return True
        time.sleep(2)
    return False


def _start_windows_desktop_voicestudio() -> bool:
    if sys.platform != "win32":
        return False
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "VoiceStudio" / "VoiceStudio.exe",
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "VoiceStudio" / "VoiceStudio.exe",
        repo_root() / "tools" / "voicestudio" / "VoiceStudio.exe",
    ]
    for exe in candidates:
        if exe.is_file():
            try:
                subprocess.Popen(
                    [str(exe)],
                    cwd=str(exe.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                for _ in range(20):
                    if voicestudio_probe_endpoint(timeout=2.0):
                        return True
                    time.sleep(2)
            except Exception as exc:
                _log.debug("VoiceStudio desktop launch failed for %s: %s", exe, exc)
    return False


def ensure_voicestudio_running(*, force: bool = False) -> bool:
    """Best-effort start when settings request VoiceStudio; no-op if already healthy."""
    global _last_start_attempt
    if voicestudio_probe_endpoint(timeout=1.5):
        return True
    if not force and not _voicestudio_wanted():
        return False
    with _supervisor_lock:
        if voicestudio_probe_endpoint(timeout=1.5):
            return True
        now = time.monotonic()
        if not force and now - _last_start_attempt < 60.0:
            return False
        _last_start_attempt = now
        if _start_docker_voicestudio():
            return True
        if _start_windows_desktop_voicestudio():
            return True
        _log.warning(
            "VoiceStudio is enabled but not reachable at %s. Install VoiceStudio or Docker, "
            "or run Setup with VoiceStudio selected.",
            voicestudio_base_url(),
        )
        return False


def schedule_voicestudio_autostart() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    def _run() -> None:
        try:
            ensure_voicestudio_running()
        except Exception:
            _log.debug("VoiceStudio autostart failed", exc_info=True)

    threading.Thread(target=_run, name="voicestudio-autostart", daemon=True).start()
