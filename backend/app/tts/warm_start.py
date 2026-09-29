from __future__ import annotations

import asyncio
import logging

from .kokoro_adapter import verify_kokoro_runtime
from .pocket_tts_adapter import pocket_tts_package_ready, verify_pocket_tts_runtime
from .voicestudio_adapter import is_voicestudio_available, verify_voicestudio_runtime

_log = logging.getLogger(__name__)

_scheduled = False


def _warmup_sync() -> None:
    state = verify_kokoro_runtime()
    if state.ready:
        _log.info("Kokoro TTS warm-start finished")
    else:
        _log.warning("Kokoro TTS warm-start failed: %s", state.last_error)
    if pocket_tts_package_ready():
        pt_state = verify_pocket_tts_runtime()
        if pt_state.ready:
            _log.info("Pocket TTS warm-start finished")
        else:
            _log.warning("Pocket TTS warm-start failed: %s", pt_state.last_error)
    if is_voicestudio_available():
        vs_state = verify_voicestudio_runtime()
        if vs_state.ready:
            _log.info("VoiceStudio warm-start finished")
        else:
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
