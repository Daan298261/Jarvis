from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from .engines import KOKORO_MODEL_DIR, is_kokoro_available

_log = logging.getLogger(__name__)

_lock = threading.Lock()
_pipelines: dict[tuple[str, str | None], Any] = {}
_scheduled = False


def get_kokoro_pipeline(lang: str, model_dir: Path | None) -> Any:
    """Return a cached Kokoro KPipeline for lang + model_dir."""
    model_key = str(model_dir.resolve()) if model_dir and model_dir.is_dir() else None
    key = (lang, model_key)
    with _lock:
        cached = _pipelines.get(key)
        if cached is not None:
            return cached
        from kokoro import KPipeline

        pipeline = KPipeline(lang_code=lang, model=str(model_dir) if model_dir else None)
        _pipelines[key] = pipeline
        return pipeline


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
    from .pack_install import ensure_kokoro_runtime

    try:
        ensure_kokoro_runtime()
    except Exception:
        _log.warning("Household voice runtime could not be prepared during warm-start", exc_info=True)
        return
    if not is_kokoro_available():
        return
    _warm_spacy_english()
    model_dir = KOKORO_MODEL_DIR if KOKORO_MODEL_DIR.is_dir() else None
    for lang in ("a", "b"):
        try:
            get_kokoro_pipeline(lang, model_dir)
        except Exception:
            _log.warning("Kokoro pipeline warm-start failed for lang=%s", lang, exc_info=True)
            break
    else:
        _log.info("Kokoro TTS warm-start finished")


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
