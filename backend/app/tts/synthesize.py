from __future__ import annotations

import asyncio
import io
import json
import logging
import wave
from pathlib import Path
from typing import Any

from ..config import repo_root
from ..voice_profiles.schema import VoiceProfile
from .engines import (
    is_chatterbox_available,
    is_piper_available,
    legacy_system_tts_available,
)
from .kokoro_adapter import kokoro_adapter, kokoro_runtime_state
from .system_sapi import legacy_tts_backend, speak_espeak, speak_pyttsx3, speak_sapi

logger = logging.getLogger(__name__)


class TtsSynthesisError(RuntimeError):
    def __init__(self, engine_id: str, profile_id: str, detail: str) -> None:
        self.engine_id = engine_id
        self.profile_id = profile_id
        self.detail = detail
        super().__init__(
            f"{engine_id} synthesis failed for {profile_id or 'unprofiled speech'}: {detail}"
        )


def _pcm_to_wav(pcm: bytes, *, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def _float32_to_pcm16(audio) -> bytes:
    import numpy as np

    arr = np.asarray(audio, dtype=np.float32)
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767.0).astype(np.int16).tobytes()


def _persona_playback() -> tuple[float, float, float] | None:
    try:
        from ..persona.named_persona import active_playback_overrides

        return active_playback_overrides()
    except Exception:
        return None


def _wav_to_float(wav: bytes):
    import numpy as np

    with wave.open(io.BytesIO(wav), "rb") as handle:
        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise RuntimeError("Neural PCM adjustments expect 16-bit WAV")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sample_rate


def _resample_linear(samples, new_len: int):
    import numpy as np

    count = int(samples.shape[0])
    if new_len <= 1 or count <= 1:
        return samples[:1]
    if new_len == count:
        return samples
    source = np.linspace(0.0, 1.0, num=count, endpoint=False)
    target = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(target, source, samples).astype(np.float32)


def apply_neural_pcm_adjustments(
    wav: bytes,
    *,
    pitch_semitones: float = 0.0,
    speaking_rate: float | None = None,
    volume: float = 1.0,
) -> bytes:
    """Pitch-shift, time-stretch, and gain on neural PCM. Never calls SAPI."""
    rate = 1.0 if speaking_rate is None else float(speaking_rate)
    neutral_rate = abs(rate - 1.0) < 1e-3
    if abs(pitch_semitones) < 1e-3 and abs(volume - 1.0) < 1e-3 and neutral_rate:
        return wav
    samples, sample_rate = _wav_to_float(wav)
    if not neutral_rate and rate > 0:
        samples = _resample_linear(samples, max(1, int(round(len(samples) / rate))))
    if abs(pitch_semitones) >= 1e-3:
        factor = 2.0 ** (float(pitch_semitones) / 12.0)
        pitched_len = max(1, int(round(len(samples) / factor)))
        original = len(samples)
        samples = _resample_linear(_resample_linear(samples, pitched_len), original)
    if abs(volume - 1.0) >= 1e-3:
        import numpy as np

        samples = np.clip(samples * float(volume), -1.0, 1.0)
    return _pcm_to_wav(_float32_to_pcm16(samples), sample_rate=sample_rate)


async def synthesize_with_engine(
    text: str,
    *,
    engine_id: str,
    profile: VoiceProfile | None = None,
    speaker_ref: str = "",
    model_dir: Path | None = None,
) -> bytes:
    engine = (engine_id or "").strip().lower()
    voice = speaker_ref or (profile.tts.speaker_ref if profile else "") or ""
    speaking_rate = profile.tts.speaking_rate if profile else 1.0
    profile_id = profile.id if profile else ""
    playback = _persona_playback()
    if engine == "kokoro":
        try:
            # Persona rate is Kokoro's speed argument. Pitch and gain stay on the PCM.
            speed = playback[0] if playback is not None else speaking_rate
            audio = await _synthesize_kokoro(
                text,
                voice=voice,
                model_dir=model_dir,
                profile=profile,
                speaking_rate=speed,
            )
            if playback is None:
                return audio
            _rate, pitch, volume = playback
            return apply_neural_pcm_adjustments(audio, pitch_semitones=pitch, speaking_rate=None, volume=volume)
        except Exception as exc:
            logger.exception("Kokoro synthesis failed for profile=%s; SAPI fallback is disabled", profile_id)
            raise TtsSynthesisError("kokoro", profile_id, str(exc)) from exc
    if engine in {"chatterbox", "chatterbox_turbo", "chatterbox-turbo"}:
        try:
            audio = await _synthesize_chatterbox(text, voice=voice)
            if playback is None:
                return audio
            rate, pitch, volume = playback
            return apply_neural_pcm_adjustments(
                audio,
                pitch_semitones=pitch,
                speaking_rate=rate,
                volume=volume,
            )
        except Exception as exc:
            logger.exception("Chatterbox synthesis failed for profile=%s; system fallback is disabled", profile_id)
            raise TtsSynthesisError("chatterbox", profile_id, str(exc)) from exc
    if engine == "piper":
        return await _synthesize_piper(text, voice=voice, profile=profile)
    if engine in {"system", "sapi", "windows", "espeak", "espeak-ng", "pyttsx3"}:
        return await _synthesize_system(
            text,
            engine=engine,
            speaker_ref=voice,
            speaking_rate=speaking_rate,
        )
    raise TtsSynthesisError(
        engine or "unknown",
        profile_id,
        f"Unknown TTS engine '{engine or 'none'}' was requested; refusing silent SAPI fallback.",
    )


async def _synthesize_kokoro(
    text: str,
    *,
    voice: str,
    model_dir: Path | None,
    profile: VoiceProfile | None,
    speaking_rate: float,
) -> bytes:
    del model_dir, profile
    state = kokoro_runtime_state()
    if not state.ready:
        raise RuntimeError(state.last_error or "Kokoro runtime is not ready")
    return await kokoro_adapter.synthesize_async(
        text,
        voice=voice or "bm_daniel",
        speed=speaking_rate,
    )


async def _synthesize_chatterbox(text: str, *, voice: str) -> bytes:
    if not is_chatterbox_available():
        raise RuntimeError(
            "Chatterbox is not installed. Use Get this voice in Settings and retry."
        )

    def _run() -> bytes:
        import torch
        from chatterbox.tts import ChatterboxTTS  # type: ignore[import-not-found]

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = ChatterboxTTS.from_pretrained(device=device)
        kwargs = {"audio_prompt_path": voice} if voice and Path(voice).is_file() else {}
        wav = model.generate(text, **kwargs)
        if isinstance(wav, bytes):
            return wav
        pcm = _float32_to_pcm16(wav)
        return _pcm_to_wav(pcm, sample_rate=int(getattr(model, "sr", 24000)))

    return await asyncio.to_thread(_run)


async def _synthesize_piper(text: str, *, voice: str, profile: VoiceProfile | None) -> bytes:
    if not is_piper_available():
        raise RuntimeError("Piper is not installed (piper binary or piper Python package).")

    onnx = _resolve_piper_onnx(voice, profile)
    if onnx is None:
        raise RuntimeError("No Piper voice ONNX found for this profile.")

    import shutil

    binary = shutil.which("piper")
    if binary:
        out_path = repo_root() / "data" / "_piper_out.wav"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            binary,
            "--model",
            str(onnx),
            "--output_file",
            str(out_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=text.encode("utf-8"))
        if proc.returncode != 0 or not out_path.is_file():
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace"))
        data = out_path.read_bytes()
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass
        return data

    def _run_python() -> bytes:
        from piper import PiperVoice  # type: ignore[import-not-found]

        voice_obj = PiperVoice.load(str(onnx))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            voice_obj.synthesize(text, handle)
        return buffer.getvalue()

    return await asyncio.to_thread(_run_python)


def _resolve_piper_onnx(voice: str, profile: VoiceProfile | None) -> Path | None:
    candidates: list[Path] = []
    if profile and profile.tts.pack_path:
        pack = repo_root() / profile.tts.pack_path
        candidates.extend(pack.glob("*.onnx"))
    if voice:
        candidates.extend((repo_root() / "models" / "tts" / "piper").glob(f"*{voice}*.onnx"))
    for path in candidates:
        if path.is_file():
            return path
    return None


async def _synthesize_system(
    text: str,
    *,
    engine: str,
    speaker_ref: str,
    speaking_rate: float,
) -> bytes:
    if not legacy_system_tts_available():
        raise RuntimeError("No legacy system TTS backend is available.")
    backend = legacy_tts_backend()
    if backend == "sapi":
        return await speak_sapi(text, speaker_ref=speaker_ref, speaking_rate=speaking_rate)
    if backend in {"espeak", "espeak-ng"}:
        return await speak_espeak(text, backend, speaker_ref=speaker_ref, speaking_rate=speaking_rate)
    return speak_pyttsx3(text, speaker_ref=speaker_ref, speaking_rate=speaking_rate)


def load_pack_manifest(pack_dir: Path) -> dict[str, Any]:
    manifest = pack_dir / "pack.json"
    if not manifest.is_file():
        return {}
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}
