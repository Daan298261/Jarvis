from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _temp_path(suffix: str = ".wav") -> Path:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(path)


def legacy_tts_backend() -> str | None:
    """Legacy OS TTS backends (SAPI / espeak / pyttsx3) used only as fallback."""
    if sys.platform == "win32":
        return "sapi"
    if shutil.which("espeak-ng"):
        return "espeak-ng"
    if shutil.which("espeak"):
        return "espeak"
    if _module_available("pyttsx3"):
        return "pyttsx3"
    return None


async def speak_sapi(
    text: str,
    *,
    speaker_ref: str = "",
    speaking_rate: float = 1.0,
) -> bytes:
    out = _temp_path(".wav")
    escaped = text.replace("'", "''")
    voice_line = ""
    if speaker_ref:
        safe_voice = speaker_ref.replace("'", "''")
        voice_line = (
            f"try {{ $s.SelectVoice('{safe_voice}') }} catch {{ "
            f"$match = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Name -like '*{safe_voice}*' }} | Select-Object -First 1; "
            "if ($null -ne $match) { $s.SelectVoice($match.VoiceInfo.Name) } }"
        )
    sapi_rate = max(-10, min(10, round((speaking_rate - 1.0) * 10)))
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"{voice_line}; "
        f"$s.Rate = {sapi_rate}; "
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


async def speak_espeak(
    text: str,
    binary_name: str,
    *,
    speaker_ref: str = "",
    speaking_rate: float = 1.0,
) -> bytes:
    binary = shutil.which(binary_name) or binary_name
    out = _temp_path(".wav")
    words_per_minute = max(80, min(450, round(175 * speaking_rate)))
    command = [binary, "-w", str(out), "-s", str(words_per_minute)]
    if speaker_ref:
        command.extend(["-v", speaker_ref])
    command.append(text)
    proc = await asyncio.create_subprocess_exec(
        *command,
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


def speak_pyttsx3(
    text: str,
    *,
    speaker_ref: str = "",
    speaking_rate: float = 1.0,
) -> bytes:
    import pyttsx3

    out = _temp_path(".wav")
    engine = pyttsx3.init()
    base_rate = int(engine.getProperty("rate") or 200)
    engine.setProperty("rate", max(80, min(450, round(base_rate * speaking_rate))))
    if speaker_ref:
        for voice in engine.getProperty("voices") or []:
            name = getattr(voice, "name", "") or ""
            vid = getattr(voice, "id", "") or ""
            if speaker_ref.lower() in name.lower() or speaker_ref.lower() in vid.lower():
                engine.setProperty("voice", vid)
                break
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
