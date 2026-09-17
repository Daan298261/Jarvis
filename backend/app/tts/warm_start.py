from __future__ import annotations

import asyncio
import logging

from .kokoro_adapter import verify_kokoro_runtime

_log = logging.getLogger(__name__)

_scheduled = False


def _warm_spacy_english() -> None:
    try:
        import spacy
    except ImportError:
        return
    for model_name in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"):
        try:
            spacy.load(model_name)
            return
        except OSError:
            continue
    try:
        spacy.blank("en")
    except Exception:
        _log.debug("spaCy English warm-start skipped", exc_info=True)


def _warmup_sync() -> None:
    _warm_spacy_english()
    state = verify_kokoro_runtime()
    if state.ready:
        _log.info("Kokoro TTS warm-start finished")
    else:
        _log.warning("Kokoro TTS warm-start failed: %s", state.last_error)


def schedule_tts_warm_start() -> None:
    """Fire-and-forget Kokoro + spaCy preload on the running event loop."""
    global _scheduled
    if _scheduled:
        return
    _scheduled = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(asyncio.to_thread(_warmup_sync))
