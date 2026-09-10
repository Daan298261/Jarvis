# RFC-0064 / 0065 / 0066 — Companion realtime voice + PC endpoint (digest)

**Full specs:** `docs/rfcs/0064-android-realtime-voice.md`, `docs/rfcs/0065-companion-pc-endpoint-bringup.md`, `docs/rfcs/0066-companion-realtime-voice-verification.md`

Android companion duplex voice over authenticated WSS; clip STT/TTS fallback. Dev bring-up uses `JARVIS_SKIP_MODEL=1` on `:4780` and optional TLS gateway on `:4781`. Cloud verifies pytest + live `/api/system`; physical-phone latency is desktop sign-off.
