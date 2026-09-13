"""Launch self-check for the initializing overlay (RFC-0082)."""
from __future__ import annotations

import os
from typing import Any, Literal

from ..config import load_settings
from ..inference.manager import MANAGER
from ..tts.engines import engine_availability, legacy_system_tts_available
from ..workers.voice import voice_status

CheckStatus = Literal["ready", "starting", "degraded", "missing"]


def _item(id: str, label: str, status: CheckStatus, detail: str) -> dict[str, str]:
    return {"id": id, "label": label, "status": status, "detail": detail}


def _overall(checks: list[dict[str, str]]) -> str:
    statuses = {item["status"] for item in checks}
    if "missing" in statuses:
        return "blocked"
    if "starting" in statuses:
        return "initializing"
    if "degraded" in statuses:
        return "degraded"
    return "ready"


async def run_self_check() -> dict[str, Any]:
    settings = load_settings()
    skip_model = os.environ.get("JARVIS_SKIP_MODEL", "").strip() in {"1", "true", "yes"}
    model = await MANAGER.snapshot(settings)
    engines = engine_availability()
    voice = voice_status()

    if model.get("loaded"):
        model_item = _item("inference", "Local inference", "ready", model.get("active_model") or "Model online")
    elif skip_model:
        model_item = _item("inference", "Local inference", "ready", "Model load skipped for this session")
    elif model.get("loading"):
        model_item = _item("inference", "Local inference", "starting", "Starting the local model")
    elif model.get("last_error"):
        model_item = _item(
            "inference",
            "Local inference",
            "degraded",
            "Model is not loaded. Chat still works; load it from Model when ready.",
        )
    else:
        model_item = _item("inference", "Local inference", "starting", "Waiting for the local model")

    kokoro = bool(engines.get("kokoro"))
    weights = bool(engines.get("kokoro_weights"))
    system_tts = bool(engines.get("system")) or legacy_system_tts_available()
    if kokoro and weights:
        voice_item = _item("household_voice", "Household voice", "ready", "Natural local voice online")
    elif kokoro or weights:
        if system_tts:
            voice_item = _item(
                "household_voice",
                "Household voice",
                "degraded",
                "Household voice is still preparing. System voice is online until then.",
            )
        else:
            voice_item = _item(
                "household_voice",
                "Household voice",
                "starting",
                "Preparing the household voice. This happens once.",
            )
    elif system_tts:
        voice_item = _item(
            "household_voice",
            "Household voice",
            "degraded",
            "System voice is online until the household voice finishes installing.",
        )
    else:
        voice_item = _item("household_voice", "Household voice", "missing", "No local speech engine is available.")

    if voice.get("stt_ready"):
        listen_item = _item("speech_recognition", "Speech recognition", "ready", "Listening is available")
    else:
        listen_item = _item(
            "speech_recognition",
            "Speech recognition",
            "degraded",
            "Typed chat works. Voice replies need local speech recognition.",
        )

    checks = [
        _item("core", "Core systems", "ready", "Jarvis API is online"),
        model_item,
        voice_item,
        listen_item,
    ]
    overall = _overall(checks)
    working_order = overall in {"ready", "degraded"}
    return {
        "ok": True,
        "overall": overall,
        "working_order": working_order,
        "headline": "All systems in working order" if working_order else "Initializing",
        "checks": checks,
    }
