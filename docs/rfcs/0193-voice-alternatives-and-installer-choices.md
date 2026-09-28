# RFC-0193: Voice Alternatives (VoiceStudio, Pocket TTS, Whisper) and Installer Choices

**Status:** implemented  
**Queue item:** Voice / STT / TTS flexibility and installer download options  
**Author:** cloud agent  
**Date:** 2026-09-28

## Problem

Jarvis default household butler speech uses Kokoro-82M (pinned 0.9.4 runtime with bundled local weights). However, users need flexibility to:
1. Integrate `debpalash/voicestudio` (local multi-engine suite with 16 TTS / 11 ASR engines) as a Kokoro alternative.
2. Utilize lightweight CPU neural speech (`pocket-tts` by Kyutai Labs) for environments where low compute/memory footprint is prioritized.
3. Configure Whisper as a selectable speech-to-text (STT) backend alongside Windows SAPI and VoiceStudio transcription.
4. Select which speech systems, neural voices, and model weights to download via checkboxes during Windows installer setup (`JarvisSetup.exe`).

## Decision

1. **VoiceStudio Integration (`VoiceStudioAdapter`):**
   - Implemented `VoiceStudioAdapter` in `backend/app/tts/voicestudio_adapter.py`.
   - Connects to local VoiceStudio server (`http://127.0.0.1:3900` or configurable `JARVIS_VOICESTUDIO_URL`).
   - Supports OpenAI-compatible speech synthesis (`POST /v1/audio/speech`), voice listing (`GET /v1/audio/voices`), and Whisper transcription (`POST /v1/audio/transcriptions`).
   - Integrated into `engines.py`, `synthesize.py`, `workers/voice.py`, and voice profile catalog (`voicestudio_clone_en_v1`).

2. **Pocket TTS Integration (`PocketTtsAdapter`):**
   - Implemented `PocketTtsAdapter` in `backend/app/tts/pocket_tts_adapter.py`.
   - Supports Kyutai Labs lightweight CPU neural TTS model (`pocket-tts`).
   - Integrated into `engines.py`, `synthesize.py`, and voice profile catalog (`pocket_tts_alba_en_v1`).

3. **Whisper STT Flexibility:**
   - Supported backend selection in `backend/app/workers/voice.py` (`faster-whisper`, `voicestudio`, `whisper.cpp`, `openai-whisper`, `windows-sapi`).
   - Exposed STT configuration in `VoiceSettings` (`active_profile_id`, `stt_backend`, `whisper_model`, `voicestudio_url`) and `SettingsUpdate` in `backend/app/api/settings.py`.

4. **Installer Checkboxes (`Jarvis.iss`, `run-installer-bootstrap.ps1`, `bootstrap.ps1`):**
   - Added selectable `[Tasks]` checkboxes in Inno Setup:
     - `dl_kokoro`: Kokoro-82M TTS neural voice (checked by default)
     - `dl_personavoices`: Persona neural voices (5 shared packs for 13 personas, checked by default)
     - `dl_whisper`: Whisper speech-to-text base model + faster-whisper (checked by default)
     - `dl_voicestudio`: VoiceStudio local multi-engine voice suite integration (unchecked by default)
     - `dl_pockettts`: Pocket TTS lightweight CPU neural voice (unchecked by default)
     - `dl_localllm`: Qwen3.5-9B GGUF weights (checked by default)
     - `dl_expert27b`: Qwen3.5-27B Expert weights (unchecked by default)
   - Updated `GetBootstrapRunParameters` in `Jarvis.iss` to pass corresponding switches (`-SkipKokoro`, `-SkipPersonaVoices`, `-InstallWhisper`, `-InstallVoiceStudio`, `-InstallPocketTTS`, `-InstallLocalLLM`, `-InstallExpert27B`).
   - Forwarded switches through `run-installer-bootstrap.ps1` to `bootstrap.ps1`.
   - Added `Ensure-WhisperModel`, `Ensure-VoiceStudio`, and `Ensure-PocketTTS` functions in `bootstrap.ps1`, while gating Kokoro and Persona voice preparation on user selection.

## Acceptance criteria

- [x] `VoiceStudioAdapter` and `PocketTtsAdapter` implemented with health probing, synthesis, and runtime state tracking.
- [x] `engines.py` recognizes `voicestudio` and `pocket_tts` in availability and engine chain dispatch.
- [x] `synthesize.py` dispatches synthesis requests to VoiceStudio and Pocket TTS adapters with persona playback overrides.
- [x] `workers/voice.py` supports STT backend selection including VoiceStudio transcription and faster-whisper.
- [x] Voice profiles and packs registered for `voicestudio_clone_en_v1` and `pocket_tts_alba_en_v1`.
- [x] Inno Setup installer tasks, parameter forwarding, and bootstrap downloader functions wired.
- [x] Unit tests pass (`python3 -m pytest tests/test_voice_alternatives.py tests/test_installer.py tests/test_rfc0070_tts.py tests/test_voice_profiles.py`).
- [x] Frontend builds cleanly (`npm --prefix frontend run build`).
