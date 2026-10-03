from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from .runtime_state import TtsRuntimeState
from .voice_runtime_config import voicestudio_auth_headers, voicestudio_base_url

VOICESTUDIO_PROBE_VOICE = "default"

logger = logging.getLogger(__name__)


def voicestudio_probe_endpoint(timeout: float = 2.0) -> bool:
    """Check whether a debpalash/voicestudio local server is listening and healthy."""
    if os.environ.get("JARVIS_DISABLE_VOICESTUDIO", "").strip().lower() in {"1", "true", "yes"}:
        return False
    base = voicestudio_base_url()
    # Check /health or /v1/models or /v1/audio/voices
    candidates = [f"{base}/health", f"{base}/v1/models", f"{base}/v1/audio/voices", f"{base}/docs"]
    for url in candidates:
        try:
            from ..policy.network_http import require_http_url_allowed

            require_http_url_allowed(url, tool="web_fetch")
            req = urllib.request.Request(url, headers=voicestudio_auth_headers())
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 400:
                    return True
        except Exception:
            continue
    return False


class VoiceStudioAdapter:
    """debpalash/voicestudio local API adapter.
    
    VoiceStudio provides OpenAI-compatible audio APIs:
    - POST /v1/audio/speech (TTS synthesis)
    - GET /v1/audio/voices (voice profiles and clones)
    - POST /v1/audio/transcriptions (ASR Whisper STT)
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._custom_url = base_url
        self._lock = threading.RLock()
        self._state: TtsRuntimeState | None = None

    @property
    def base_url(self) -> str:
        if self._custom_url:
            return self._custom_url.rstrip("/")
        return voicestudio_base_url()

    def _base_state(self, *, last_error: str = "") -> TtsRuntimeState:
        package_ready = True
        endpoint_ready = voicestudio_probe_endpoint(timeout=1.5)
        if not last_error:
            if not endpoint_ready:
                last_error = f"VoiceStudio server is not responding at {self.base_url}."
            else:
                last_error = "VoiceStudio runtime has not passed its synthesis health probe yet."
        return TtsRuntimeState(
            engine_id="voicestudio",
            package_ready=package_ready,
            assets_ready=endpoint_ready,
            pipeline_ready=endpoint_ready,
            synthesis_verified=False,
            model_id="voicestudio-local",
            speaker_ref=VOICESTUDIO_PROBE_VOICE,
            device="local-api",
            last_error=last_error if not endpoint_ready else "",
        )

    def runtime_state(self) -> TtsRuntimeState:
        with self._lock:
            if self._state is None:
                self._state = self._base_state()
            return self._state

    def reset(self) -> TtsRuntimeState:
        with self._lock:
            self._state = self._base_state()
            return self._state

    def is_available(self) -> bool:
        return voicestudio_probe_endpoint(timeout=1.5)

    def list_voices(self, timeout: float = 3.0) -> list[dict[str, Any]]:
        url = f"{self.base_url}/v1/audio/voices"
        try:
            from ..policy.network_http import require_http_url_allowed

            require_http_url_allowed(url, tool="web_fetch")
            req = urllib.request.Request(url, headers=voicestudio_auth_headers())
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "voices" in data:
                    return data["voices"]
        except Exception as exc:
            logger.debug("Failed to list voices from VoiceStudio: %s", exc)
        return []

    def synthesize(
        self,
        text: str,
        *,
        voice: str = "default",
        model: str = "tts-1",
        speed: float = 1.0,
        response_format: str = "wav",
        timeout: float = 8.0,
    ) -> bytes:
        """Call VoiceStudio /v1/audio/speech endpoint to generate speech audio."""
        url = f"{self.base_url}/v1/audio/speech"
        payload = {
            "model": model or "tts-1",
            "input": text,
            "voice": voice or VOICESTUDIO_PROBE_VOICE,
            "speed": float(speed),
            "response_format": response_format,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = voicestudio_auth_headers()
        headers["Content-Type"] = "application/json"
        from ..policy.network_http import require_http_url_allowed

        require_http_url_allowed(url, tool="web_fetch")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"VoiceStudio synthesis HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise RuntimeError(f"VoiceStudio synthesis request failed: {exc}") from exc

    async def synthesize_async(
        self,
        text: str,
        *,
        voice: str = "default",
        model: str = "tts-1",
        speed: float = 1.0,
        response_format: str = "wav",
        timeout: float = 8.0,
    ) -> bytes:
        return await asyncio.to_thread(
            self.synthesize,
            text,
            voice=voice,
            model=model,
            speed=speed,
            response_format=response_format,
            timeout=timeout,
        )

    def transcribe(
        self,
        audio_data: bytes,
        filename: str = "audio.wav",
        *,
        model: str = "whisper-1",
        language: str = "",
        timeout: float = 60.0,
    ) -> str:
        """Send audio to VoiceStudio /v1/audio/transcriptions (Whisper ASR)."""
        url = f"{self.base_url}/v1/audio/transcriptions"
        boundary = "----JarvisVoiceStudioFormBoundary" + str(int(time.time() * 1000))
        lines: list[bytes] = []

        def add_field(name: str, val: str):
            lines.append(f"--{boundary}".encode("utf-8"))
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
            lines.append(b"")
            lines.append(val.encode("utf-8"))

        add_field("model", model or "whisper-1")
        if language:
            add_field("language", language)

        lines.append(f"--{boundary}".encode("utf-8"))
        lines.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode("utf-8"))
        lines.append(b"Content-Type: audio/wav")
        lines.append(b"")
        lines.append(audio_data)
        lines.append(f"--{boundary}--".encode("utf-8"))
        lines.append(b"")

        body = b"\r\n".join(lines)
        headers = voicestudio_auth_headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        from ..policy.network_http import require_http_url_allowed

        require_http_url_allowed(url, tool="web_fetch")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("text", "").strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"VoiceStudio transcription HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise RuntimeError(f"VoiceStudio transcription request failed: {exc}") from exc

    async def transcribe_async(
        self,
        audio_data: bytes,
        filename: str = "audio.wav",
        *,
        model: str = "whisper-1",
        language: str = "",
        timeout: float = 60.0,
    ) -> str:
        return await asyncio.to_thread(
            self.transcribe,
            audio_data,
            filename=filename,
            model=model,
            language=language,
            timeout=timeout,
        )

    def verify(self, *, force: bool = False) -> TtsRuntimeState:
        with self._lock:
            if not force and self._state is not None and self._state.synthesis_verified:
                return self._state
        started = time.perf_counter()
        try:
            audio = self.synthesize(
                "Voice systems online.",
                voice=VOICESTUDIO_PROBE_VOICE,
                speed=1.0,
                timeout=10.0,
            )
            if len(audio) < 100:
                raise RuntimeError("Generated audio is unexpectedly small")
            state = TtsRuntimeState(
                engine_id="voicestudio",
                package_ready=True,
                assets_ready=True,
                pipeline_ready=True,
                synthesis_verified=True,
                model_id="voicestudio-local",
                speaker_ref=VOICESTUDIO_PROBE_VOICE,
                device="local-api",
            )
        except Exception as exc:
            state = self._base_state(last_error=str(exc))
        with self._lock:
            self._state = state
        logger.info(
            "voicestudio_runtime_probe %s",
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


voicestudio_adapter = VoiceStudioAdapter()


def voicestudio_runtime_state() -> TtsRuntimeState:
    return voicestudio_adapter.runtime_state()


def reset_voicestudio_runtime_state() -> TtsRuntimeState:
    return voicestudio_adapter.reset()


def is_voicestudio_available() -> bool:
    if os.environ.get("JARVIS_DISABLE_VOICESTUDIO", "").strip().lower() in {"1", "true", "yes"}:
        return False
    state = voicestudio_adapter.runtime_state()
    if state.ready:
        return True
    return voicestudio_adapter.is_available()


def verify_voicestudio_runtime(*, force: bool = False) -> TtsRuntimeState:
    return voicestudio_adapter.verify(force=force)
