from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import models_dir


@dataclass
class VoiceSTTError(RuntimeError):
    """Recoverable speech-to-text failure with install guidance."""

    message: str
    code: str = "stt_unavailable"
    install_hint: str = ""
    status: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


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


def _find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import playwright

        driver = Path(playwright.__file__).resolve().parent / "driver"
        for candidate in driver.rglob("ffmpeg*"):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
            if candidate.is_file() and candidate.suffix.lower() in {".exe", ""}:
                return str(candidate)
    except Exception:
        pass
    return None


def _temp_path(suffix: str = ".wav") -> Path:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(path)


def stt_backend() -> str | None:
    if local_whisper_model() is not None and _module_available("faster_whisper"):
        return "faster-whisper"
    if sys.platform == "win32":
        return "windows-sapi"
    if shutil.which("whisper-cli") or shutil.which("whisper.cpp"):
        return "whisper.cpp"
    if _module_available("whisper"):
        return "openai-whisper"
    if _module_available("faster_whisper"):
        return "faster-whisper"
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


def stt_install_hint(backend: str | None = None) -> str:
    chosen = backend or stt_backend() or "faster-whisper"
    if chosen == "windows-sapi":
        return (
            "Windows speech recognition is built in. If transcription fails, install optional "
            "faster-whisper for higher accuracy: pip install faster-whisper "
            "(or re-run Jarvis setup after adding it to requirements)."
        )
    if chosen == "faster-whisper":
        return (
            "Install faster-whisper in the Jarvis venv: pip install faster-whisper. "
            "Optional: place a model in models/whisper/ or set JARVIS_WHISPER_MODEL."
        )
    if chosen == "whisper.cpp":
        return (
            "Install whisper.cpp on PATH and place ggml-base.bin in models/whisper/, "
            "or pip install faster-whisper for an easier local STT path."
        )
    return (
        "Install faster-whisper (pip install faster-whisper) and place a model in models/whisper/, "
        "or set JARVIS_WHISPER_MODEL."
    )


def voice_status() -> dict[str, Any]:
    stt = stt_backend()
    tts = tts_backend()
    model = local_whisper_model()
    ffmpeg = _find_ffmpeg()
    stt_ready = False
    if stt == "faster-whisper":
        stt_ready = True
    elif stt == "windows-sapi":
        stt_ready = True
    elif stt in {"openai-whisper", "whisper.cpp"}:
        stt_ready = model is not None
    detail_parts = []
    if stt_ready:
        detail_parts.append(f"STT={stt}")
        if model:
            detail_parts.append(f"model={model.name}")
        elif stt == "windows-sapi":
            detail_parts.append("engine=Windows.Speech")
            if ffmpeg:
                detail_parts.append("ffmpeg=available")
            else:
                detail_parts.append("ffmpeg=missing (webm uploads need ffmpeg or faster-whisper)")
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
        "ffmpeg_available": bool(ffmpeg),
        "install_hint": stt_install_hint(stt),
    }


def _write_upload(data: bytes, suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    handle.write(data)
    handle.close()
    return Path(handle.name)


async def _convert_to_wav(source: Path) -> Path:
    if source.suffix.lower() == ".wav":
        return source
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise VoiceSTTError(
            "Uploaded audio must be WAV unless ffmpeg is available for conversion.",
            code="stt_needs_ffmpeg",
            install_hint=(
                "Install ffmpeg on PATH, install Playwright Chromium (bootstrap already does), "
                "or pip install faster-whisper which bundles audio decoding."
            ),
        )
    target = source.with_suffix(".wav")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-ar",
        "16000",
        "-ac",
        "1",
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise VoiceSTTError(
            stderr.decode("utf-8", errors="replace") or "Audio conversion to WAV failed.",
            code="stt_convert_failed",
            install_hint=stt_install_hint("faster-whisper"),
        )
    return target


async def transcribe_audio(data: bytes, filename: str = "audio.webm") -> str:
    status = voice_status()
    if not status["stt_ready"]:
        raise VoiceSTTError(
            status["detail"],
            code="stt_unavailable",
            install_hint=status.get("install_hint") or stt_install_hint(),
            status=status,
        )
    suffix = Path(filename).suffix or ".webm"
    path = _write_upload(data, suffix)
    converted: Path | None = None
    try:
        backend = status["stt"]
        if backend == "faster-whisper":
            return _transcribe_faster_whisper(path, status.get("model_path") or None)
        if backend == "windows-sapi":
            converted = await _convert_to_wav(path)
            return await _transcribe_windows_sapi(converted)
        if backend == "whisper.cpp":
            return await _transcribe_whisper_cpp(path, Path(status["model_path"]))
        if backend == "openai-whisper":
            return _transcribe_openai_whisper(path, Path(status["model_path"]) if status.get("model_path") else None)
        raise VoiceSTTError(
            "No local STT backend is available.",
            code="stt_unavailable",
            install_hint=stt_install_hint(),
            status=status,
        )
    finally:
        for candidate in {path, converted}:
            if candidate is None:
                continue
            try:
                candidate.unlink(missing_ok=True)
            except Exception:
                pass


def _transcribe_faster_whisper(path: Path, model_path: str | None) -> str:
    from faster_whisper import WhisperModel

    name = model_path or "base"
    try:
        model = WhisperModel(name, local_files_only=True)
    except Exception as exc:
        raise VoiceSTTError(
            "faster-whisper is installed but no local model is cached. "
            "Place a model in models/whisper/ or set JARVIS_WHISPER_MODEL. "
            f"({exc})",
            code="stt_model_missing",
            install_hint=(
                "Download a Whisper model into models/whisper/ or set JARVIS_WHISPER_MODEL. "
                "Example: huggingface-cli download Systran/faster-whisper-base --local-dir models/whisper/base"
            ),
        ) from exc
    segments, _info = model.transcribe(str(path))
    text = " ".join(segment.text.strip() for segment in segments if getattr(segment, "text", "")).strip()
    if not text:
        raise VoiceSTTError(
            "Whisper produced an empty transcript.",
            code="stt_empty",
            install_hint="Speak clearly and retry, or check the microphone input level.",
        )
    return text


def _transcribe_openai_whisper(path: Path, model_path: Path | None) -> str:
    import whisper

    if model_path and model_path.is_file():
        model = whisper.load_model(str(model_path))
    else:
        download_root = str(models_dir() / "whisper")
        try:
            model = whisper.load_model("base", download_root=download_root, in_memory=False)
        except Exception as exc:
            raise VoiceSTTError(
                "openai-whisper has no local model. Put base.pt in models/whisper/. "
                f"({exc})",
                code="stt_model_missing",
                install_hint="Place base.pt in models/whisper/ or pip install faster-whisper.",
            ) from exc
    result = model.transcribe(str(path))
    text = str(result.get("text") or "").strip()
    if not text:
        raise VoiceSTTError(
            "Whisper produced an empty transcript.",
            code="stt_empty",
            install_hint="Speak clearly and retry, or check the microphone input level.",
        )
    return text


async def _transcribe_whisper_cpp(path: Path, model: Path) -> str:
    binary = shutil.which("whisper-cli") or shutil.which("whisper.cpp")
    if not binary:
        raise VoiceSTTError(
            "whisper.cpp CLI is not on PATH.",
            code="stt_unavailable",
            install_hint=stt_install_hint("whisper.cpp"),
        )
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
        raise VoiceSTTError(
            stderr.decode("utf-8", errors="replace") or "whisper.cpp failed",
            code="stt_failed",
            install_hint=stt_install_hint("whisper.cpp"),
        )
    text = txt.read_text(encoding="utf-8", errors="replace").strip()
    try:
        txt.unlink(missing_ok=True)
    except Exception:
        pass
    if not text:
        raise VoiceSTTError(
            "whisper.cpp produced an empty transcript.",
            code="stt_empty",
            install_hint="Speak clearly and retry, or check the microphone input level.",
        )
    return text


async def _transcribe_windows_sapi(path: Path) -> str:
    if sys.platform != "win32":
        raise VoiceSTTError(
            "Windows speech recognition is only available on Windows.",
            code="stt_unavailable",
            install_hint=stt_install_hint("faster-whisper"),
        )
    wav_path = str(path).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
        f"$engine.SetInputToWaveFile('{wav_path}'); "
        "$result = $engine.Recognize(); "
        "if ($null -eq $result -or [string]::IsNullOrWhiteSpace($result.Text)) { exit 2 }; "
        "$result.Text"
    )
    proc = await asyncio.create_subprocess_exec(
        "powershell",
        "-NoProfile",
        "-Command",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    text = stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode == 2 or not text:
        raise VoiceSTTError(
            "Windows speech recognition did not detect any speech.",
            code="stt_empty",
            install_hint=(
                "Speak clearly and retry. For better accuracy install faster-whisper: "
                "pip install faster-whisper"
            ),
        )
    if proc.returncode != 0:
        raise VoiceSTTError(
            stderr.decode("utf-8", errors="replace") or "Windows speech recognition failed.",
            code="stt_failed",
            install_hint=stt_install_hint("windows-sapi"),
        )
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
    out = _temp_path(".wav")
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
    binary = shutil.which(binary_name) or binary_name
    out = _temp_path(".wav")
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

    out = _temp_path(".wav")
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
