# Companion realtime voice (RFC-0064 digest)

**Full specs:** `docs/rfcs/0064-android-realtime-voice.md`, `docs/rfcs/0066-companion-realtime-voice-verification.md`

Push-to-talk on the Android companion can use a duplex WSS session instead of one-shot clip upload/download.

## Transport

- Path: `/api/companion/voice/realtime` (also via mobile gateway WebSocket proxy)
- Auth: `Authorization: Bearer <device-session>` + `X-Jarvis-Device: <id>` headers only (never query tokens)
- Audio: PCM16LE mono @ 16 kHz, base64 JSON frames, monotonic `seq`, memory-only buffers

## Client flow

1. `hello` → server `session` (limits + `session_id`)
2. `start_turn` → `turn`
3. `audio` frames → optional `partial` transcripts
4. `end_turn` → `final` transcript → streaming `tts` sentence chunks → `done`
5. `interrupt` cancels playback / clears the turn buffer
6. HTTPS `/voice/transcribe` and `/voice/speak` remain the clip fallback

## Verify (dev)

```bash
python3 -m pytest tests/test_mobile_realtime_voice.py tests/test_mobile_companion.py -q
curl -sS http://127.0.0.1:4780/api/system >/dev/null
```

**Cloud verification (2026-09-10):** 47 focused companion/realtime/connectivity/pairing tests passed;
live `:4780` `/api/system` + portal SPA 200; gateway `:4781` requires device auth (401 without);
authenticated WSS `hello` → `session` → replay rejection passed. Physical-phone latency and live
voice quality are **desktop/phone sign-off**, not cloud-verified.
