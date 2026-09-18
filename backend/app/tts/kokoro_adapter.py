from __future__ import annotations

import asyncio
import importlib.metadata
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

KOKORO_HF_REPO = "hexgrad/Kokoro-82M"
KOKORO_MODEL_ID = "kokoro-82m"
KOKORO_MODEL_DIR = models_dir() / "tts" / KOKORO_MODEL_ID
KOKORO_PACKAGE_VERSION = "0.9.4"
SOUNDFILE_PACKAGE_VERSION = "0.14.0"
KOKORO_PROBE_VOICE = "bm_george"

logger = logging.getLogger(__name__)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def kokoro_package_ready() -> bool:
    if os.environ.get("JARVIS_DISABLE_KOKORO", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return (
        _module_available("kokoro")
        and _module_available("soundfile")
        and _package_version("kokoro") == KOKORO_PACKAGE_VERSION
        and _package_version("soundfile") == SOUNDFILE_PACKAGE_VERSION
    )


def kokoro_assets_ready(model_dir: Path | None = None) -> bool:
    root = model_dir or KOKORO_MODEL_DIR
    return (
        root.is_dir()
        and (root / "config.json").is_file()
        and any(root.glob("*.pth"))
        and (root / "voices" / f"{KOKORO_PROBE_VOICE}.pt").is_file()
    )


def is_kokoro_installable() -> bool:
    return os.environ.get("JARVIS_DISABLE_KOKORO", "").strip().lower() not in {"1", "true", "yes"}


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


class KokoroAdapter:
    """Pinned Kokoro 0.9.4 adapter backed only by Jarvis-bundled assets."""

    def __init__(self, model_dir: Path = KOKORO_MODEL_DIR) -> None:
        self.model_dir = model_dir
        self._lock = threading.RLock()
        self._model: Any | None = None
        self._pipelines: dict[str, Any] = {}
        self._state: TtsRuntimeState | None = None

    def _base_state(self, *, last_error: str = "") -> TtsRuntimeState:
        package_ready = kokoro_package_ready()
        assets_ready = kokoro_assets_ready(self.model_dir)
        if not last_error:
            if not package_ready:
                last_error = (
                    f"Kokoro runtime requires kokoro=={KOKORO_PACKAGE_VERSION} and "
                    f"soundfile=={SOUNDFILE_PACKAGE_VERSION}."
                )
            elif not assets_ready:
                last_error = f"Kokoro model or voice assets are incomplete under {self.model_dir}."
            else:
                last_error = "Kokoro runtime has not passed its synthesis health probe yet."
        return TtsRuntimeState(
            engine_id="kokoro",
            package_ready=package_ready,
            assets_ready=assets_ready,
            pipeline_ready=False,
            synthesis_verified=False,
            model_id=KOKORO_MODEL_ID,
            speaker_ref=KOKORO_PROBE_VOICE,
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
            self._pipelines.clear()
            self._state = self._base_state()
            return self._state

    def _local_model_files(self) -> tuple[Path, Path]:
        config_path = self.model_dir / "config.json"
        preferred_weights = self.model_dir / "kokoro-v1_0.pth"
        weight_paths = [preferred_weights] if preferred_weights.is_file() else sorted(self.model_dir.glob("*.pth"))
        if not config_path.is_file() or not weight_paths:
            raise FileNotFoundError(
                f"Kokoro runtime is incomplete under {self.model_dir}; config.json and model weights are required."
            )
        return config_path, weight_paths[0]

    def _voice_ref(self, voice: str) -> str:
        resolved: list[str] = []
        for speaker in (item.strip() for item in voice.split(",")):
            if not speaker:
                continue
            supplied = Path(speaker)
            if supplied.is_file():
                resolved.append(str(supplied.resolve()))
                continue
            filename = speaker if speaker.endswith(".pt") else f"{speaker}.pt"
            bundled = self.model_dir / "voices" / filename
            if not bundled.is_file():
                raise FileNotFoundError(
                    f"Kokoro voice '{speaker}' is missing from {self.model_dir / 'voices'}. "
                    "Repair the household voice from Settings."
                )
            resolved.append(str(bundled.resolve()))
        if not resolved:
            raise RuntimeError("No Kokoro speaker was selected.")
        return ",".join(resolved)

    def get_pipeline(self, lang: str) -> Any:
        with self._lock:
            cached = self._pipelines.get(lang)
            if cached is not None:
                return cached
            if not kokoro_package_ready():
                raise RuntimeError(self._base_state().last_error)
            if not kokoro_assets_ready(self.model_dir):
                raise RuntimeError(self._base_state().last_error)

            from kokoro import KModel, KPipeline

            if self._model is None:
                config_path, weights_path = self._local_model_files()
                self._model = KModel(
                    repo_id=KOKORO_HF_REPO,
                    config=str(config_path),
                    model=str(weights_path),
                ).eval()
            pipeline = KPipeline(
                lang_code=lang,
                repo_id=KOKORO_HF_REPO,
                model=self._model,
            )
            self._pipelines[lang] = pipeline
            return pipeline

    def _synthesize_unverified(self, text: str, *, voice: str, speed: float) -> bytes:
        chosen = (voice or KOKORO_PROBE_VOICE).strip()
        lang = "b" if chosen.startswith("b") else "a"
        pipeline = self.get_pipeline(lang)
        voice_ref = self._voice_ref(chosen)
        chunks: list[bytes] = []
        for _graphemes, _phonemes, audio in pipeline(text, voice=voice_ref, speed=speed):
            if audio is not None:
                pcm = _float32_to_pcm16(audio)
                if pcm:
                    chunks.append(pcm)
        if not chunks:
            raise RuntimeError("Kokoro produced no audio")
        return _pcm_to_wav(b"".join(chunks), sample_rate=24000)

    def synthesize(self, text: str, *, voice: str, speed: float) -> bytes:
        state = self.runtime_state()
        if not state.ready:
            raise RuntimeError(state.last_error or "Kokoro runtime is not ready")
        return self._synthesize_unverified(text, voice=voice, speed=speed)

    async def synthesize_async(self, text: str, *, voice: str, speed: float) -> bytes:
        return await asyncio.to_thread(self.synthesize, text, voice=voice, speed=speed)

    def verify(self, *, force: bool = False) -> TtsRuntimeState:
        with self._lock:
            current = self.runtime_state()
            if current.ready and not force:
                return current
            if force:
                self._model = None
                self._pipelines.clear()
                self._state = self._base_state()

        started = time.perf_counter()
        try:
            audio = self._synthesize_unverified(
                "Voice systems online.",
                voice=KOKORO_PROBE_VOICE,
                speed=0.96,
            )
            if len(audio) < 1024:
                raise RuntimeError("Generated WAV is unexpectedly small")
            state = TtsRuntimeState(
                engine_id="kokoro",
                package_ready=True,
                assets_ready=True,
                pipeline_ready=True,
                synthesis_verified=True,
                model_id=KOKORO_MODEL_ID,
                speaker_ref=KOKORO_PROBE_VOICE,
                device="cpu",
            )
        except Exception as exc:
            state = self._base_state(last_error=str(exc))
        with self._lock:
            self._state = state
        logger.info(
            "voice_runtime_probe %s",
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


kokoro_adapter = KokoroAdapter()


def kokoro_runtime_state() -> TtsRuntimeState:
    return kokoro_adapter.runtime_state()


def reset_kokoro_runtime_state() -> TtsRuntimeState:
    return kokoro_adapter.reset()


def verify_kokoro_runtime(*, force: bool = False) -> TtsRuntimeState:
    return kokoro_adapter.verify(force=force)


async def verify_kokoro_runtime_async(*, force: bool = False) -> TtsRuntimeState:
    return await kokoro_adapter.verify_async(force=force)
