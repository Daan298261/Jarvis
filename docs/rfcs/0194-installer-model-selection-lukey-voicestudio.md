# RFC-0194: Installer model selection, lukey03 9B default, faster-whisper, VoiceStudio autostart

**Status:** implemented  
**Date:** 2026-09-29

## Decision

1. Default agent brain GGUF: `lukey03/Qwen3.5-9B-abliterated-GGUF` (`Qwen3.5-9B-abliterated-Q4_K_M.gguf`).
2. Ornith 1.5 9B Q4_K_M remains bundled bootstrap / offline backup.
3. Inno Setup **Local AI models** wizard page selects optional downloads (lukey 9B default checked, legacy Abiray Q8/Q6, Expert 27B).
4. `faster-whisper` pip package always installed in bootstrap; base model weights remain optional via Whisper task.
5. VoiceStudio: bootstrap clones repo + pulls Docker image when selected; Jarvis autostarts Docker/desktop API when `voice.voicestudio_autostart` or STT/TTS VoiceStudio preference is enabled.
