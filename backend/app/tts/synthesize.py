from __future__ import annotations

import asyncio
import io
import json
import wave
from pathlib import Path
from typing import Any

from ..config import repo_root
from ..voice_profiles.schema import VoiceProfile
from .engines import (
    CHATTERBOX_MODEL_DIR,
    KOKORO_MODEL_DIR,
    is_chatterbox_available,
    is_kokoro_available,
    is_piper_available,
    legacy_system_tts_available,
    resolve_pack_model_dir,
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


async def synthesize_with_engine(
    text: str,
    *,
    engine_id: str,
    profile: VoiceProfile | None = None,
    speaker_ref: str = "",
    model_dir: Path | None = None,
) -> bytes:
    engine = (engine_id or "system").strip().lower()
    voice = speaker_ref or (profile.tts.speaker_ref if profile else "") or ""
    if engine == "kokoro":
        return await _synthesize_kokoro(text, voice=voice, model_dir=model_dir, profile=profile)
    if engine == "chatterbox":
        return await _synthesize_chatterbox(text, voice=voice)
    if engine == "piper":
        return await _synthesize_piper(text, voice=voice, profile=profile)
    return await _synthesize_system(text, engine=engine, speaker_ref=voice)


async def _synthesize_kokoro(
    text: str,
    *,
    voice: str,
    model_dir: Path | None,
    profile: VoiceProfile | None,
) -> bytes:
    if not is_kokoro_available(model_dir=model_dir):
        raise RuntimeError(
            "Kokoro TTS is not ready. Install the kokoro package and stage Kokoro-82M weights "
            f"under {KOKORO_MODEL_DIR} (Windows Setup bundles the default butler pack)."
        )

    resolved_dir = model_dir
    if resolved_dir is None and profile is not None:
        resolved_dir = resolve_pack_model_dir(profile)

    def _run() -> bytes:
        from kokoro import KPipeline

        lang = "b" if voice.startswith("b") else "a"
        pipeline = KPipeline(lang_code=lang, model=str(resolved_dir) if resolved_dir else None)
        chosen = voice or "bm_george"
        chunks: list[bytes] = []
        sample_rate = 24000
        for _gs, _ps, audio in pipeline(text, voice=chosen, speed=1.0):
            if audio is None:
                continue
            chunks.append(_float32_to_pcm16(audio))
        if not chunks:
            raise RuntimeError("Kokoro produced no audio")
        pcm = b"".join(chunks)
        return _pcm_to_wav(pcm, sample_rate=sample_rate)

    return await asyncio.to_thread(_run)


async def _synthesize_chatterbox(text: str, *, voice: str) -> bytes:
    if not is_chatterbox_available():
        raise RuntimeError(
            "Chatterbox is opt-in. Set JARVIS_TTS_CHATTERBOX=1, pip install chatterbox, "
            f"and stage weights under {CHATTERBOX_MODEL_DIR}."
        )

    def _run() -> bytes:
        from chatterbox import ChatterboxTTS  # type: ignore[import-not-found]

        model = ChatterboxTTS.from_pretrained(str(CHATTERBOX_MODEL_DIR))
        wav = model.generate(text, voice=voice or None)
        if isinstance(wav, bytes):
            return wav
        pcm = _float32_to_pcm16(wav)
        return _pcm_to_wav(pcm)

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


async def _synthesize_system(text: str, *, engine: str, speaker_ref: str) -> bytes:
    if not legacy_system_tts_available():
        raise RuntimeError("No legacy system TTS backend is available.")
    from ..workers import voice as voice_worker

    backend = voice_worker.legacy_tts_backend()
    if backend == "sapi":
        return await voice_worker._speak_sapi(text, speaker_ref=speaker_ref)
    if backend in {"espeak", "espeak-ng"}:
        return await voice_worker._speak_espeak(text, backend, speaker_ref=speaker_ref)
    return voice_worker._speak_pyttsx3(text, speaker_ref=speaker_ref)


def load_pack_manifest(pack_dir: Path) -> dict[str, Any]:
    manifest = pack_dir / "pack.json"
    if not manifest.is_file():
        return {}
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}
