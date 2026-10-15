# RFC-0221: Companion reliability and Offgrid

**Status:** accepted
**Author:** Codex, requested by Daan
**Date:** 2026-10-15

## Problem
Samsung assistant entry points are incomplete; offline banners crowd chat; notifications churn; desktop restarts interrupt sessions. Users need compact local Q&A and an optional Offgrid destination.

## Decision
Implement this user-requested bughunt as one PR against development. Add voice-assist entry, assistant settings status, stable notifications, bounded inference memory, pinned 1.7B Q3 alongside Q4, automatic session recovery, and an opt-in pylon Offgrid tab with local chat and existing maps/knowledge readers. Offgrid chat requires a verified abliterated/heretic catalog model and never routes to desktop.

## Acceptance criteria
- Assistant handles ASSIST and VOICE_ASSIST and exposes current role/settings.
- Home/chat have compact status; persistent offline detail lives in notifications/More.
- Notification updates preserve scroll and ongoing-condition identity.
- Session expiry after desktop restart retries once without dropping pairing or replaying arbitrary writes.
- Q3 download is revision/hash/size pinned; low-memory models use 2K context and smaller native microbatches.
- More offers Offgrid with confirmation before adding/removing its bottom tab. Offgrid contains maps, knowledge and strictly local minimal-refusal chat.
- Assess tiny voice and phone LoRa support using upstream evidence; report hardware/runtime limitations honestly.
- Android tests, APK builds/lint/runtime ZIP checks and backend tests pass, or exact environment failures are recorded. Samsung side-button, RAM, restart and visual acceptance require physical phone.

## Likely files
Android companion UI, API transport, catalogs, JNI, Android tests; backend mobile catalog.

## Research
- Android metadata parser requires both sessionService and recognitionService: https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/service/voice/VoiceInteractionServiceInfo.java . Previous ANZU metadata omitted recognitionService, so the framework rejected the voice interactor. Register a forwarding recognition service and exclude ANZU from its own platform STT candidates.
- Qwen3 1.7B Abliterated Q3_K_M: https://huggingface.co/mradermacher/Qwen3-1.7B-abliterated-GGUF ; revision ef85d5f367b9b49842f0ab88faf07e35d6dfa505, 939538560 bytes, SHA-256 3968be1d143c0a1c333887b0cb7d62b9a3d41848eb941c620f38c379e06a1388. Q4 already ships as default, 1107409024 bytes. Approximate 2 GiB working-memory goal is not a measured phone result.
- Inflect Nano v2: https://github.com/owenawsong/Inflect ; https://huggingface.co/owensong/Inflect-Nano-v2/tree/71d70b00c8d9f9c3ca145e024b3351d327d98c51 . 15971083-byte PyTorch weights, fixed English male, Apache-2.0. No downloadable ONNX model at assessment; Android integration needs compatible export/frontend and listening/RAM validation. Keep platform offline TTS/Pocket functional; no fake install row.
- https://meshtastic.org/ and https://github.com/meshtastic/meshtastic/blob/master/docs/software/android/user/connections.md : ordinary phones require external LoRa hardware over BLE/USB/TCP. Offer Meshtastic launch/install guidance. Live reception and radio audio transcription require supported hardware/protocol and remain unverified; text packets do not contain speech.

## Out of scope
Desktop installer release, unrelated PR #644, unsupported claims of built-in phone LoRa or physical-device acceptance.
