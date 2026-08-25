from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.voice import stt_status, tts_status, voice_status
from app.voice.audio import is_wav, write_wav_bytes
from app.voice.stt import transcribe_wav
from app.voice.tts import synthesize_wav


def _tone(seconds: float = 0.4, rate: int = 16000) -> bytes:
    samples = [int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(int(rate * seconds))]
    return write_wav_bytes(samples, rate)


class VoiceAudioTests(unittest.TestCase):
    def test_wav_header(self) -> None:
        data = _tone()
        self.assertTrue(is_wav(data))
        self.assertGreater(len(data), 44)


class VoiceStatusTests(unittest.TestCase):
    def test_whisper_reports_faster_whisper_when_installed(self) -> None:
        status = stt_status()
        self.assertIn("available", status)
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            self.assertFalse(status["available"])
            return
        self.assertTrue(status["available"])
        self.assertEqual(status["engine"], "faster-whisper")

    def test_whisper_unavailable_without_engine(self) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "faster_whisper":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            status = stt_status()
        self.assertFalse(status["available"])
        self.assertIn("faster-whisper", status["reason"])

    def test_tts_available_on_windows(self) -> None:
        status = tts_status()
        if sys.platform != "win32":
            self.skipTest("Windows SAPI")
        self.assertTrue(status["available"])
        self.assertEqual(status["engine"], "sapi")

    def test_combined_status(self) -> None:
        payload = voice_status()
        self.assertIn("stt", payload)
        self.assertIn("tts", payload)
        self.assertIn("whisper", payload)
        self.assertIn("ready", payload)


class VoiceEngineTests(unittest.TestCase):
    def test_transcribe_rejects_short_audio(self) -> None:
        data = _tone(seconds=0.02)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            handle.write(data)
            path = Path(handle.name)
        try:
            with self.assertRaises(ValueError):
                transcribe_wav(path)
        finally:
            path.unlink(missing_ok=True)

    def test_transcribe_uses_whisper(self) -> None:
        data = _tone()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            handle.write(data)
            path = Path(handle.name)
        fake_model = SimpleNamespace(transcribe=lambda *_a, **_k: ([SimpleNamespace(text=" hello jarvis ")], None))
        try:
            with (
                patch("app.voice.stt.stt_status", return_value={"available": True}),
                patch("app.voice.stt._load", return_value=fake_model),
            ):
                text = transcribe_wav(path)
            self.assertEqual(text, "hello jarvis")
        finally:
            path.unlink(missing_ok=True)

    def test_speak_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            synthesize_wav("   ")

    def test_sapi_writes_wav(self) -> None:
        if sys.platform != "win32":
            self.skipTest("Windows SAPI")
        if not tts_status()["available"]:
            self.skipTest("TTS unavailable")
        path = synthesize_wav("Jarvis local TTS check.")
        try:
            data = path.read_bytes()
            self.assertTrue(is_wav(data))
            self.assertGreater(len(data), 1000)
        finally:
            path.unlink(missing_ok=True)


class VoiceApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_creates_task_from_text(self) -> None:
        from app.api.voice import VoiceIn, voice_command

        fake = SimpleNamespace(id="voice-task-1", status="queued")
        with patch("app.api.voice.AGENT.create_task", AsyncMock(return_value=fake)) as create:
            payload = await voice_command(VoiceIn(text="turn on the lights", autonomy="trusted"))
        create.assert_awaited_once()
        self.assertEqual(payload["id"], "voice-task-1")
        self.assertEqual(payload["task_id"], "voice-task-1")
        self.assertEqual(payload["prompt"], "turn on the lights")

    async def test_command_rejects_blank_text(self) -> None:
        from fastapi import HTTPException

        from app.api.voice import VoiceIn, voice_command

        with self.assertRaises(HTTPException) as raised:
            await voice_command(VoiceIn(text="  "))
        self.assertEqual(raised.exception.status_code, 400)

    async def test_status_endpoint(self) -> None:
        from app.api.voice import voice_info

        payload = await voice_info()
        self.assertIn("stt", payload)
        self.assertIn("tts", payload)
        self.assertIn("whisper", payload)

    async def test_speak_returns_wav(self) -> None:
        from app.api.voice import SpeakIn, speak

        if sys.platform != "win32":
            self.skipTest("Windows SAPI")
        response = await speak(SpeakIn(text="ok"))
        self.assertEqual(response.media_type, "audio/wav")
        self.assertTrue(response.body.startswith(b"RIFF"))


if __name__ == "__main__":
    unittest.main()
