# RFC-0064: Android realtime voice transport

**Status:** accepted  
**Author:** Codex, at the owner's request  
**Date:** 2026-09-10

## Problem

The Android companion can record speech for server-side STT and play server-generated
TTS in the same voice catalog as the desktop. Those operations currently exchange a
complete recording or WAV response. Calls use WebRTC, but conversational push-to-talk
does not yet stream partial transcripts or TTS audio. Voice-profile routing must also
select the profile's real engine and speaker instead of merely validating its ID.

## Decision

Add a low-latency duplex voice session to the existing companion gateway. Keep TTS and
STT on the Jarvis host by default so the phone stays light and matches the desktop
voice. The phone may run only local capture, playback, VAD and optional wake-word code;
any downloadable on-device model must be opt-in and no larger than 50 MiB.

Reuse the existing P-256 device identity, short-lived device session and pinned TLS.
Use WSS for conversational streams or the existing authenticated WebRTC channel when
media negotiation is already active. Give every voice turn an unpredictable ID, bind
it to the authenticated device and conversation, enforce sequence numbers, duration
and byte limits, reject replayed frames, and apply per-device rate limits. Do not place
bearer tokens in URLs, relay logs or push payloads. Do not persist raw audio unless the
owner explicitly enables retention. Relay payloads remain opaque.

Route selected voice profiles through their declared engine and speaker reference on
the Jarvis host. Preserve the complete-clip HTTPS endpoints as a retry-safe fallback.
Interrupting playback must cancel server generation and release temporary files.

## Acceptance criteria

- [ ] Android displays partial transcripts and begins playback before full TTS completion.
- [ ] The selected voice sounds the same through desktop and Android for the same profile.
- [ ] Reconnect resumes only the current turn and cannot replay or cross device sessions.
- [ ] Pinned TLS/device authentication protect direct and relay streams; secrets never
  appear in URLs, logs, APK assets or push payloads.
- [ ] Audio is memory-only by default, bounded, rate limited and cancelled on interruption.
- [ ] Existing HTTPS clip STT/TTS remains functional as fallback.
- [ ] Unit, integration and Android tests cover auth, replay, limits, cancellation,
  reconnect and profile routing; physical-device latency is recorded separately.

## Implementation prompt

> Implement RFC `docs/rfcs/0064-android-realtime-voice.md` on a new isolated branch
> from the latest `development`, with a PR against `development`. Reuse the existing
> companion identity, pinned transport, relay, calls and voice-profile modules. Do not
> introduce a second authentication or conversation system. Complete code and focused
> tests, run Android build/lint/unit checks and the relevant backend suite, then push the
> branch and open a draft PR. Leave physical-device latency and live voice quality as
> explicit desktop/phone sign-off items.

## Likely files

- `backend/app/api/companion.py`
- `backend/app/mobile/gateway.py`
- `backend/app/mobile/media.py`
- `backend/app/workers/voice.py`
- `services/mobile-relay/`
- `android/app/src/main/java/com/jarvis/companion/`
- `tests/test_mobile_media.py`
