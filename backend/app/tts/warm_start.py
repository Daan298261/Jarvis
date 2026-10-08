from __future__ import annotations

import asyncio
import logging

from .kokoro_adapter import verify_kokoro_runtime
from .pocket_tts_adapter import pocket_tts_package_ready, verify_pocket_tts_runtime
from .voicestudio_adapter import is_voicestudio_available, verify_voicestudio_runtime

_log = logging.getLogger(__name__)

_scheduled = False
_last_report: dict[str, str] = {}


def last_warm_report() -> dict[str, str]:
    return dict(_last_report)


def _warm_kokoro_langs() -> None:
    from .kokoro_adapter import kokoro_adapter

    for lang in ("a", "b"):
        key = f"kokoro_{lang}"
        try:
            kokoro_adapter.get_pipeline(lang)
            _last_report[key] = "warm"
            _log.info("Kokoro pipeline %s warm", lang)
        except Exception as exc:
            _last_report[key] = f"skipped: {exc}"[:240]
            _log.warning("Kokoro pipeline %s warm-start skipped: %s", lang, exc)


def _active_persona_engine() -> str:
    try:
        from ..persona.named_persona import CATALOG, active_persona_id
        from ..voice_profiles.catalog import get_catalog

        persona = CATALOG.get(active_persona_id())
        voice_id = getattr(persona, "voice_profile_id", "") if persona else ""
        profile = get_catalog().get(voice_id) if voice_id else None
        if profile is None:
            return ""
        return profile.tts.resolved_engine_id()
    except Exception:
        return ""


def _warm_persona_engine() -> None:
    engine = _active_persona_engine()
    _last_report["persona_engine"] = engine or "default"
    if not engine or engine == "kokoro":
        _last_report["persona"] = "kokoro" if engine == "kokoro" else "default_kokoro"
        return
    if engine in {"chatterbox", "chatterbox_turbo", "chatterbox-turbo"}:
        _last_report["persona"] = "chatterbox_checked_with_vram"
        return
    _last_report["persona"] = f"noted:{engine}"


def _chatterbox_vram_ok() -> tuple[bool, str]:
    try:
        from ..config import load_settings
        from ..hardware import detect_hardware

        settings = load_settings()
        policy = str(getattr(settings.tts, "loading_policy", "lazy") or "lazy")
        if policy == "cpu-preferred" or bool(getattr(settings.tts, "prefer_cpu_fallback", False)):
            return False, "cpu_preferred"
        hw = detect_hardware()
        free = hw.vram_free_mib
        if free is None:
            return False, "vram_probe_unavailable"
        # Leave the worker and the Kokoro voice room. Do not evict either.
        if int(free) < 2560:
            return False, f"vram_tight: free_mib={free}"
        return True, f"free_mib={free}"
    except Exception as exc:
        return False, str(exc)[:200]


def _warm_chatterbox_if_fit() -> None:
    from .engines import is_chatterbox_available

    if not is_chatterbox_available():
        _last_report["chatterbox"] = "not_available"
        return
    ok, reason = _chatterbox_vram_ok()
    if not ok:
        _last_report["chatterbox"] = f"skipped: {reason}"
        _log.info("Chatterbox warm-start skipped (%s); worker and Kokoro stay resident", reason)
        return
    try:
        from .synthesize import _cached_chatterbox_model

        _cached_chatterbox_model("cuda")
        _last_report["chatterbox"] = f"warm: {reason}"
        _log.info("Chatterbox warm-start finished (%s)", reason)
    except Exception as exc:
        _last_report["chatterbox"] = f"failed: {exc}"[:240]
        _log.warning("Chatterbox warm-start failed: %s", exc)


def _warmup_sync() -> None:
    global _last_report
    _last_report = {}
    _warm_kokoro_langs()
    state = verify_kokoro_runtime()
    if state.ready:
        _last_report["kokoro_verify"] = "ready"
        _log.info("Kokoro TTS warm-start finished")
    else:
        _last_report["kokoro_verify"] = f"failed: {state.last_error}"[:240]
        _log.warning("Kokoro TTS warm-start failed: %s", state.last_error)
    _warm_persona_engine()
    _warm_chatterbox_if_fit()
    if pocket_tts_package_ready():
        pt_state = verify_pocket_tts_runtime()
        if pt_state.ready:
            _last_report["pocket"] = "warm"
            _log.info("Pocket TTS warm-start finished")
        else:
            _last_report["pocket"] = f"failed: {pt_state.last_error}"[:240]
            _log.warning("Pocket TTS warm-start failed: %s", pt_state.last_error)
    if is_voicestudio_available():
        vs_state = verify_voicestudio_runtime()
        if vs_state.ready:
            _last_report["voicestudio"] = "warm"
            _log.info("VoiceStudio warm-start finished")
        else:
            _last_report["voicestudio"] = f"failed: {vs_state.last_error}"[:240]
            _log.warning("VoiceStudio warm-start failed: %s", vs_state.last_error)


def schedule_tts_warm_start() -> None:
    """Fire-and-forget Kokoro / Pocket / VoiceStudio preload on the running event loop."""
    global _scheduled
    if _scheduled:
        return
    _scheduled = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(asyncio.to_thread(_warmup_sync))
