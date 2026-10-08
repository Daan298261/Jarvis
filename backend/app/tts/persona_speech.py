"""One speech path for every model.

Front, worker, and Laya text all become audio here. The voice is the
active persona's neural pack. Which model wrote the sentence does not
choose an engine or a speaker.

Persona *binding* still fails closed (RFC-0137): selecting Aegir, Bragi,
Hermes, or Maia does not succeed when Chatterbox is not installed, and
``windows_natural_en_v1`` is never a persona voice. Speech of an
already-bound persona uses the existing neural engine chain (RFC-0070):
if Chatterbox cannot take VRAM without crowding the worker, this path
skips it and speaks with Kokoro instead of going silent or evicting the
9B/27B.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from ..config import load_settings
from ..persona.named_persona import CATALOG, _appearance_for
from ..voice_profiles.catalog import WINDOWS_NATURAL_VOICE_PROFILE_ID, get_catalog
from ..voice_profiles.ip_guard import contains_forbidden_ip_term
from ..workers.voice import SynthesizedSpeech, synthesize_speech_result

# Same floor warm-start uses before it will load Chatterbox beside the worker.
CHATTERBOX_VRAM_FLOOR_MIB = 2560
SPEECH_LANES = ("front", "worker", "laya")
_VRAM_CACHE_TTL_SECONDS = 30.0
_vram_cache: tuple[float, tuple[bool, str]] | None = None
_CHATTERBOX_ENGINES = frozenset({"chatterbox", "chatterbox_turbo", "chatterbox-turbo"})
_SYSTEM_ENGINES = frozenset({"system", "sapi", "windows", "espeak", "espeak-ng", "pyttsx3"})
_KNOWN_NEURAL_IDS = frozenset(
    {
        "butler_original_v1",
        "dry_butler_original_v1",
        "tactical_aide_original_v1",
        "synthetic_command_original_v1",
        "chatterbox_expressive_en_v1",
        "pocket_tts_alba_en_v1",
        "voicestudio_clone_en_v1",
    }
)

_TRACE_LIMIT = 64
_trace: list[dict[str, str]] = []


def _note(entry: dict[str, str]) -> None:
    _trace.append(entry)
    if len(_trace) > _TRACE_LIMIT:
        del _trace[:-_TRACE_LIMIT]


class SpeechRefused(RuntimeError):
    """The line must not be spoken. Never substitute Windows SAPI."""

    def __init__(self, reason: str, *, persona_id: str = "", profile_id: str = "") -> None:
        self.reason = reason
        self.persona_id = persona_id
        self.profile_id = profile_id
        super().__init__(reason)


@dataclass(frozen=True)
class SpeechVoice:
    lane: str
    persona_id: str
    profile_id: str
    engine_id: str
    playback: tuple[float, float, float]
    refused: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "lane": self.lane,
            "persona_id": self.persona_id,
            "profile_id": self.profile_id,
            "engine_id": self.engine_id,
            "path": "persona_speech.resolve_speaking_voice",
            "refused": "1" if self.refused else "0",
            "reason": self.reason,
        }


def reset_speech_trace() -> None:
    _trace.clear()


def recent_speech_trace() -> list[dict[str, str]]:
    return [dict(item) for item in _trace]


def speech_lane_for_model(lane: str, model: str = "") -> str:
    """Label the producing lane. The label never selects a voice."""
    raw_lane = (lane or "").strip().lower()
    raw_model = (model or "").strip().lower()
    if raw_lane == "laya" or raw_model.startswith("laya") or "laya-multilingual" in raw_model:
        return "laya"
    if raw_lane == "front":
        return "front"
    return "worker"


def reset_chatterbox_block_cache() -> None:
    global _vram_cache
    _vram_cache = None


def chatterbox_speech_blocked() -> tuple[bool, str]:
    """True when loading Chatterbox for this line would crowd the worker.

    Synchronous: it calls ``detect_hardware``, which can run ``nvidia-smi``
    with a 12s timeout. Call this only from ``_chatterbox_block_for_speech``.
    Enqueue must not call it.
    """
    try:
        from ..hardware import detect_hardware

        free = detect_hardware().vram_free_mib
    except Exception as exc:
        return True, f"vram_probe_failed:{exc}"[:180]
    if free is None:
        return True, "vram_probe_unavailable"
    if int(free) < CHATTERBOX_VRAM_FLOOR_MIB:
        return True, f"vram_tight:free_mib={free}"
    return False, f"free_mib={free}"


async def _chatterbox_block_for_speech() -> tuple[bool, str]:
    """Run the VRAM probe off the event-loop thread and reuse it briefly."""
    global _vram_cache
    now = time.monotonic()
    if _vram_cache is not None and (now - _vram_cache[0]) < _VRAM_CACHE_TTL_SECONDS:
        return _vram_cache[1]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, chatterbox_speech_blocked)
    _vram_cache = (time.monotonic(), result)
    return result


def _main_persona_id(settings) -> str:
    active = (settings.named_personas.active_id or "").strip()
    if active in CATALOG:
        return active
    return "anzu"


def _acceptable_neural_id(profile_id: str) -> bool:
    pid = (profile_id or "").strip()
    if not pid or pid == WINDOWS_NATURAL_VOICE_PROFILE_ID or contains_forbidden_ip_term(pid):
        return False
    profile = get_catalog().get(pid)
    if profile is None:
        if pid in _KNOWN_NEURAL_IDS:
            return True
        return any(row.voice_profile_id == pid for row in CATALOG.values())
    return profile.tts.resolved_engine_id() not in _SYSTEM_ENGINES


def _engine_id_for(profile_id: str) -> str:
    profile = get_catalog().get(profile_id)
    if profile is not None:
        return profile.tts.resolved_engine_id()
    if "chatterbox" in profile_id:
        return "chatterbox"
    if "pocket" in profile_id:
        return "pocket_tts"
    if "voicestudio" in profile_id:
        return "voicestudio"
    return "kokoro"


def _playback_for(settings, persona_id: str) -> tuple[float, float, float]:
    appearance = _appearance_for(settings, persona_id)
    return (
        float(appearance.speaking_rate),
        float(appearance.pitch),
        float(appearance.volume),
    )


def _neural_profile_for_main(settings, persona_id: str) -> str:
    """Roster or already-bound neural pack. Never Windows SAPI."""
    row = CATALOG[persona_id]
    store = settings.named_personas
    appearance = _appearance_for(settings, persona_id)
    candidates: list[str] = []
    if persona_id == _main_persona_id(settings):
        activated = (store.activated_voice_profile_id or "").strip()
        if activated:
            candidates.append(activated)
    override = (appearance.voice_profile_id or "").strip()
    if override:
        candidates.append(override)
    candidates.append(row.voice_profile_id)
    for candidate in candidates:
        if _acceptable_neural_id(candidate):
            return candidate
    return ""


def resolve_speaking_voice(*, lane: str, model: str = "") -> SpeechVoice:
    """Resolve the active persona voice. Does not synthesize or probe VRAM."""
    resolved_lane = speech_lane_for_model(lane, model)
    settings = load_settings()
    main_id = _main_persona_id(settings)
    profile_id = _neural_profile_for_main(settings, main_id)
    refused = False
    reason = ""
    if not profile_id:
        refused = True
        reason = "active persona has no neural voice"
    engine_id = _engine_id_for(profile_id) if profile_id else ""
    playback = _playback_for(settings, main_id)
    voice = SpeechVoice(
        lane=resolved_lane,
        persona_id=main_id,
        profile_id=profile_id,
        engine_id=engine_id,
        playback=playback,
        refused=refused,
        reason=reason,
    )
    _note(voice.as_dict())
    return voice


async def speak_text(
    text: str,
    *,
    lane: str = "worker",
    model: str = "",
) -> SynthesizedSpeech:
    """Turn text into speech in the active persona's voice.

    This is the only model-speech entry. It does not install packages and
    it does not run a TTS health synthesis; engine readiness stays on the
    cached runtime probe. The Chatterbox VRAM probe runs here, off the
    event-loop thread, and is not part of enqueue.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise RuntimeError("text is required")
    voice = resolve_speaking_voice(lane=lane, model=model)
    if voice.refused:
        raise SpeechRefused(voice.reason or "speech refused", persona_id=voice.persona_id, profile_id=voice.profile_id)
    if voice.profile_id == WINDOWS_NATURAL_VOICE_PROFILE_ID or voice.engine_id in _SYSTEM_ENGINES:
        raise SpeechRefused(
            "Windows SAPI is not a persona voice.",
            persona_id=voice.persona_id,
            profile_id=voice.profile_id,
        )
    blocked: tuple[str, ...] = ()
    reason = voice.reason
    if voice.engine_id in _CHATTERBOX_ENGINES:
        blocked_now, block_reason = await _chatterbox_block_for_speech()
        if blocked_now:
            blocked = tuple(sorted(_CHATTERBOX_ENGINES))
            reason = block_reason
    result = await synthesize_speech_result(
        cleaned,
        voice_profile_id=voice.profile_id,
        blocked_engines=blocked,
        playback=voice.playback,
        allow_neural_fallback=True,
    )
    _note(
        {
            **voice.as_dict(),
            "path": "persona_speech.speak_text",
            "actual_engine": result.engine_id,
            "reason": reason,
        }
    )
    return result
