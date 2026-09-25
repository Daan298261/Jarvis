"""RFC-0140 voice path routing — Leader/Kokoro preferred online; on-device for Mode A/B."""

from __future__ import annotations

from typing import Any, Literal

SttRoute = Literal["gateway", "on_device", "install"]
TtsRoute = Literal["host_neural", "on_device", "install"]
VoiceMode = Literal["online", "A", "B"]


def decide_voice_route(
    *,
    leader_reachable: bool,
    realtime_voice_healthy: bool,
    host_tts_healthy: bool,
    stt_pack_status: str,
    tts_pack_status: str,
    local_llm_ready: bool = False,
    prefer_on_device_frontend: bool = False,
) -> dict[str, Any]:
    """Return STT/TTS route preference. Never silent-replaces host neural while online+healthy."""
    ready = {"ready", "running"}

    if leader_reachable and realtime_voice_healthy and host_tts_healthy and not prefer_on_device_frontend:
        return {
            "mode": "online",
            "stt": "gateway",
            "tts": "host_neural",
            "banner": None,
            "error": None,
        }

    if leader_reachable and (not realtime_voice_healthy or not host_tts_healthy):
        stt: SttRoute = "on_device" if stt_pack_status in ready else "install"
        tts: TtsRoute = "on_device" if tts_pack_status in ready else "install"
        error = None
        if stt == "install" or tts == "install":
            error = "Host voice failed and on-device voice packs are not installed — open More → Voice"
        return {
            "mode": "A",
            "stt": stt,
            "tts": tts,
            "banner": "Host voice unavailable — using on-device voice packs" if error is None else None,
            "error": error,
        }

    if not leader_reachable:
        mode: VoiceMode = "B" if local_llm_ready else "A"
        stt = "on_device" if stt_pack_status in ready else "install"
        tts = "on_device" if tts_pack_status in ready else "install"
        error = None
        if stt == "install" or tts == "install":
            error = "Leader unreachable — install on-device voice packs in More → Voice to listen or speak"
        return {
            "mode": mode,
            "stt": stt,
            "tts": tts,
            "banner": "On-device voice (Leader unreachable)" if error is None else None,
            "error": error,
        }

    # Leader reachable, prefer optional low-latency front-end that still hands off to Leader
    return {
        "mode": "online",
        "stt": "gateway",
        "tts": "host_neural",
        "banner": "On-device front-end active — Leader remains authoritative",
        "error": None,
        "frontend_only": True,
    }
