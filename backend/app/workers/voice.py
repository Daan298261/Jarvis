from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..config import models_dir


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def whisper_model_candidates() -> list[Path]:
    env = os.environ.get("JARVIS_WHISPER_MODEL") or ""
    root = models_dir() / "whisper"
    names = [
        "ggml-base.bin",
        "ggml-base.en.bin",
        "base.pt",
        "tiny.pt",
        "small.pt",
    ]
    out: list[Path] = []
    if env:
        out.append(Path(env).expanduser())
    for name in names:
        out.append(root / name)
    return [path for path in out if str(path).strip()]


def local_whisper_model() -> Path | None:
    for path in whisper_model_candidates():
        if path.is_file():
            return path
    return None


def stt_backend() -> str | None:
    if _module_available("faster_whisper"):
        return "faster-whisper"
    if shutil.which("whisper-cli") or shutil.which("whisper.cpp"):
        return "whisper.cpp"
    if _module_available("whisper"):
        return "openai-whisper"
    return None


def tts_backend() -> str | None:
    if sys.platform == "win32":
        return "sapi"
    if shutil.which("espeak-ng"):
        return "espeak-ng"
    if shutil.which("espeak"):
        return "espeak"
    if _module_available("pyttsx3"):
        return "pyttsx3"
    return None


def voice_status() -> dict[str, Any]:
    stt = stt_backend()
    tts = tts_backend()
    model = local_whisper_model()
    stt_ready = False
    if stt == "faster-whisper":
        stt_ready = True
    elif stt in {"openai-whisper", "whisper.cpp"}:
        stt_ready = model is not None
    detail_parts = []
    if stt_ready:
        detail_parts.append(f"STT={stt}")
        if model:
            detail_parts.append(f"model={model.name}")
    else:
        detail_parts.append(
            "STT missing. Install faster-whisper and place a model in models/whisper/ "
            "or set JARVIS_WHISPER_MODEL. Cloud speech APIs are not used."
        )
    if tts:
        detail_parts.append(f"TTS={tts}")
    else:
        detail_parts.append("TTS missing. Windows SAPI, espeak-ng, or pyttsx3 provide local speech.")
    return {
        "id": "voice",
        "name": "Voice STT/TTS",
        "kind": "native",
        "available": bool(stt_ready or tts),
        "status": "ready" if stt_ready or tts else "missing",
        "detail": " ".join(detail_parts),
        "stt": stt,
        "tts": tts,
        "stt_ready": bool(stt_ready),
        "tts_ready": bool(tts),
        "model_path": str(model) if model else "",
    }


def _write_upload(data: bytes, suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    handle.write(data)
    handle.close()
    return Path(handle.name)


async def transcribe_audio(data: bytes, filename: str = "audio.webm") -> str:
    status = voice_status()
    if not status["stt_ready"]:
        raise RuntimeError(status["detail"])
    suffix = Path(filename).suffix or ".webm"
    path = _write_upload(data, suffix)
    try:
        backend = status["stt"]
        if backend == "faster-whisper":
            return _transcribe_faster_whisper(path, status.get("model_path") or None)
        if backend == "whisper.cpp":
            return await _transcribe_whisper_cpp(path, Path(status["model_path"]))
        if backend == "openai-whisper":
            return _transcribe_openai_whisper(path, Path(status["model_path"]) if status.get("model_path") else None)
        raise RuntimeError("No local STT backend is available.")
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _transcribe_faster_whisper(path: Path, model_path: str | None) -> str:
    from faster_whisper import WhisperModel

    name = model_path or "base"
    try:
        model = WhisperModel(name, local_files_only=True)
    except Exception as exc:
        raise RuntimeError(
            "faster-whisper is installed but no local model is cached. "
            "Place a model in models/whisper/ or set JARVIS_WHISPER_MODEL. "
            f"({exc})"
        ) from exc
    segments, _info = model.transcribe(str(path))
    text = " ".join(segment.text.strip() for segment in segments if getattr(segment, "text", "")).strip()
    if not text:
        raise RuntimeError("Whisper produced an empty transcript.")
    return text


def _transcribe_openai_whisper(path: Path, model_path: Path | None) -> str:
    import whisper

    kwargs: dict[str, Any] = {}
    if model_path and model_path.is_file():
        model = whisper.load_model(str(model_path))
    else:
        kwargs["download_root"] = str(models_dir() / "whisper")
        try:
            model = whisper.load_model("base", download_root=kwargs["download_root"], in_memory=False)
        except Exception as exc:
            raise RuntimeError(
                "openai-whisper has no local model. Put base.pt in models/whisper/. "
                f"({exc})"
            ) from exc
    result = model.transcribe(str(path))
    text = str(result.get("text") or "").strip()
    if not text:
        raise RuntimeError("Whisper produced an empty transcript.")
    return text


async def _transcribe_whisper_cpp(path: Path, model: Path) -> str:
    import asyncio

    binary = shutil.which("whisper-cli") or shutil.which("whisper.cpp")
    if not binary:
        raise RuntimeError("whisper.cpp CLI is not on PATH.")
    out_base = path.with_suffix("")
    proc = await asyncio.create_subprocess_exec(
        binary,
        "-m",
        str(model),
        "-f",
        str(path),
        "-otxt",
        "-of",
        str(out_base),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    txt = Path(str(out_base) + ".txt")
    if proc.returncode != 0 or not txt.is_file():
        raise RuntimeError(stderr.decode("utf-8", errors="replace") or "whisper.cpp failed")
    text = txt.read_text(encoding="utf-8", errors="replace").strip()
    try:
        txt.unlink(missing_ok=True)
    except Exception:
        pass
    if not text:
        raise RuntimeError("whisper.cpp produced an empty transcript.")
    return text


async def synthesize_speech(text: str) -> bytes:
    cleaned = (text or "").strip()
    if not cleaned:
        raise RuntimeError("text is required")
    backend = tts_backend()
    if not backend:
        raise RuntimeError(
            "No local TTS backend is available. On Windows, SAPI is used automatically. "
            "Otherwise install espeak-ng or pyttsx3."
        )
    if backend == "sapi":
        return await _speak_sapi(cleaned)
    if backend in {"espeak", "espeak-ng"}:
        return await _speak_espeak(cleaned, backend)
    return _speak_pyttsx3(cleaned)


async def _speak_sapi(text: str) -> bytes:
    import asyncio

    out = Path(tempfile.mkstemp(suffix=".wav")[1])
    escaped = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{out}'); "
        f"$s.Speak('{escaped}'); "
        "$s.Dispose()"
    )
    proc = await asyncio.create_subprocess_exec(
        "powershell",
        "-NoProfile",
        "-Command",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace") or "Windows SAPI TTS failed")
    data = out.read_bytes()
    try:
        out.unlink(missing_ok=True)
    except Exception:
        pass
    return data


async def _speak_espeak(text: str, binary_name: str) -> bytes:
    import asyncio

    binary = shutil.which(binary_name) or binary_name
    out = Path(tempfile.mkstemp(suffix=".wav")[1])
    proc = await asyncio.create_subprocess_exec(
        binary,
        "-w",
        str(out),
        text,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace") or "espeak TTS failed")
    data = out.read_bytes()
    try:
        out.unlink(missing_ok=True)
    except Exception:
        pass
    return data


def _speak_pyttsx3(text: str) -> bytes:
    import pyttsx3

    out = Path(tempfile.mkstemp(suffix=".wav")[1])
    engine = pyttsx3.init()
    engine.save_to_file(text, str(out))
    engine.runAndWait()
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError("pyttsx3 did not write audio")
    data = out.read_bytes()
    try:
        out.unlink(missing_ok=True)
    except Exception:
        pass
    return data
