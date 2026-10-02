from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import logging
import os
import threading
import time
import wave
from pathlib import Path
from typing import Any

from ..config import models_dir
from .runtime_state import TtsRuntimeState

logger = logging.getLogger(__name__)

_POCKET_TTS_NEED_BYTES = 512 * 1024**2
POCKET_TTS_MODEL_DIR = models_dir() / "tts" / "pocket-tts"
POCKET_TTS_DEFAULT_VOICE = "alba"


def resolved_pocket_tts_model_dir() -> Path:
    """`models/tts/pocket-tts`, or extra-drive `Jarvis/models/tts/pocket-tts` when C: cannot fit."""
    from ..inference.lmstudio_catalog import resolved_tts_model_dir

    dest = resolved_tts_model_dir("pocket-tts", markers=(), need_bytes=_POCKET_TTS_NEED_BYTES)
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def pocket_tts_package_ready() -> bool:
    if os.environ.get("JARVIS_DISABLE_POCKET_TTS", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return _module_available("pocket_tts")


def pocket_tts_assets_ready(model_dir: Path | None = None) -> bool:
    if not pocket_tts_package_ready():
        return False
    root = model_dir if model_dir is not None else resolved_pocket_tts_model_dir()
    if root.is_dir() and (any(root.glob("*.safetensors")) or any(root.glob("*.pt"))):
        return True
    return pocket_tts_package_ready()


def _pcm_to_wav(pcm: bytes, *, sample_rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def _float32_to_pcm16(audio: Any) -> bytes:
    import numpy as np

    arr = np.asarray(audio, dtype=np.float32)
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767.0).astype(np.int16).tobytes()


class PocketTtsAdapter:
    """Kyutai Labs Pocket TTS lightweight CPU neural text-to-speech adapter."""

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir_override = model_dir
        self._lock = threading.RLock()
        self._model: Any | None = None
        self._state: TtsRuntimeState | None = None

    @property
    def model_dir(self) -> Path:
        if self._model_dir_override is not None:
            return self._model_dir_override
        return resolved_pocket_tts_model_dir()

    def _base_state(self, *, last_error: str = "") -> TtsRuntimeState:
        package_ready = pocket_tts_package_ready()
        assets_ready = pocket_tts_assets_ready(self.model_dir)
        if not last_error:
            if not package_ready:
                last_error = "Pocket TTS runtime requires 'pip install pocket-tts'."
            elif not assets_ready:
                last_error = f"Pocket TTS assets are missing under {self.model_dir}."
            else:
                last_error = "Pocket TTS runtime has not passed its synthesis health probe yet."
        return TtsRuntimeState(
            engine_id="pocket_tts",
            package_ready=package_ready,
            assets_ready=assets_ready,
            pipeline_ready=False,
            synthesis_verified=False,
            model_id="pocket-tts",
            speaker_ref=POCKET_TTS_DEFAULT_VOICE,
            device="cpu",
            last_error=last_error,
        )

    def runtime_state(self) -> TtsRuntimeState:
        with self._lock:
            if self._state is None:
                self._state = self._base_state()
            return self._state

    def reset(self) -> TtsRuntimeState:
        with self._lock:
            self._model = None
            self._state = self._base_state()
            return self._state

    def is_available(self) -> bool:
        if not pocket_tts_package_ready():
            return False
        state = self.runtime_state()
        return state.ready

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            if not pocket_tts_package_ready():
                raise RuntimeError("pocket_tts package is not installed (pip install pocket-tts).")
            from ..inference.lmstudio_catalog import apply_huggingface_home
            from pocket_tts import TTSModel

            apply_huggingface_home()
            self._model = TTSModel.load_model()
            return self._model

    def synthesize(
        self,
        text: str,
        *,
        voice: str = POCKET_TTS_DEFAULT_VOICE,
        speed: float = 1.0,
    ) -> bytes:
        """Generate audio with pocket-tts, returning 16-bit PCM WAV bytes."""
        model = self._get_model()
        # Voice prompt resolution
        target_voice = voice or POCKET_TTS_DEFAULT_VOICE
        try:
            voice_state = model.get_state_for_audio_prompt(target_voice)
        except Exception:
            # Fallback or default prompt
            voice_state = model.get_state_for_audio_prompt(POCKET_TTS_DEFAULT_VOICE)

        audio = model.generate_audio(voice_state, text)
        if speed and abs(float(speed) - 1.0) >= 1e-3:
            import numpy as np

            samples = np.asarray(audio, dtype=np.float32)
            new_len = max(1, int(round(len(samples) / float(speed))))
            source = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
            target = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
            audio = np.interp(target, source, samples).astype(np.float32)
        pcm = _float32_to_pcm16(audio)
        sample_rate = int(getattr(model, "sample_rate", 24000))
        return _pcm_to_wav(pcm, sample_rate=sample_rate)

    async def synthesize_async(
        self,
        text: str,
        *,
        voice: str = POCKET_TTS_DEFAULT_VOICE,
        speed: float = 1.0,
    ) -> bytes:
        return await asyncio.to_thread(self.synthesize, text, voice=voice, speed=speed)

    def verify(self, *, force: bool = False) -> TtsRuntimeState:
        with self._lock:
            if not force and self._state is not None and self._state.synthesis_verified:
                return self._state
        if not pocket_tts_package_ready():
            state = self._base_state(last_error="pocket_tts is not installed (pip install pocket-tts)")
            with self._lock:
                self._state = state
            return state

        started = time.perf_counter()
        try:
            audio = self.synthesize("Voice systems online.", voice=POCKET_TTS_DEFAULT_VOICE)
            if len(audio) < 100:
                raise RuntimeError("Generated audio is unexpectedly small")
            state = TtsRuntimeState(
                engine_id="pocket_tts",
                package_ready=True,
                assets_ready=True,
                pipeline_ready=True,
                synthesis_verified=True,
                model_id="pocket-tts",
                speaker_ref=POCKET_TTS_DEFAULT_VOICE,
                device="cpu",
            )
        except Exception as exc:
            state = self._base_state(last_error=str(exc))
        with self._lock:
            self._state = state
        logger.info(
            "pocket_tts_runtime_probe %s",
            json.dumps(
                {
                    **state.to_dict(),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                },
                sort_keys=True,
            ),
        )
        return state

    async def verify_async(self, *, force: bool = False) -> TtsRuntimeState:
        return await asyncio.to_thread(self.verify, force=force)


pocket_tts_adapter = PocketTtsAdapter()


def pocket_tts_runtime_state() -> TtsRuntimeState:
    return pocket_tts_adapter.runtime_state()


def reset_pocket_tts_runtime_state() -> TtsRuntimeState:
    return pocket_tts_adapter.reset()


def is_pocket_tts_available() -> bool:
    if os.environ.get("JARVIS_DISABLE_POCKET_TTS", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return pocket_tts_adapter.is_available()


def verify_pocket_tts_runtime(*, force: bool = False) -> TtsRuntimeState:
    return pocket_tts_adapter.verify(force=force)
