# RFC-0234: Android solar context and live replies

**Status:** accepted

**Author:** Codex, requested by Daan

**Date:** 2026-10-17

## Problem

The phone orb resembles a solar system but lacks planets and context feedback. Local Qwen replies appear stalled because generated tokens are buffered until completion; phone tools can run ten silent inference passes.

## Decision

Extend orb mode with the eight planets, sun, rings, glow, thinking pulses and a seeded twinkling star field. Fade stars as the active phone model context fills, using native prompt and generated token counts; unknown context stays explicitly unknown. Preserve humanoid mode. Stream ordinary replies to Home and Chat, show elapsed work and tool stages, and record load/first-token/total latency. Reuse safe transformer prompt prefixes with a full-reset fallback for unsupported memory removal.

## Acceptance criteria

User follow-up (2026-10-17): extend this phone-responsiveness ticket to model download screens. Publish per-model connecting/downloading/retrying/verifying/ready/error/paused state immediately, including byte counts and transfer rate. Use readable model cards and shared progress feedback on Models, first-run setup, and Memory & speed. Allow cancellation of blocked HTTP reads while preserving partial files for resume; prevent duplicate starts. Do not claim measured on-phone inference speed without live timings.

- Eight distinguishable planets orbit at independent, continuous speeds; Saturn has rings.
- Thinking visibly pulses sun and rings; reduced motion freezes movement and twinkling.
- Star visibility decreases monotonically with context use, restores on a new conversation, and has an accessible context label.
- Ordinary local output becomes visible before generation ends; internal tool JSON stays hidden.
- Stage progress and elapsed seconds remain visible during long loads, prefill and phone actions.
- Native prefix reuse resets on model changes and fails safely; logs distinguish first-token time from total time.
- Android tests, native compilation, APK assembly and lint pass. Physical phone speed remains a separate acceptance gate.
- Model download feedback appears before the first byte; retry and verification remain visibly busy, completion requires successful verification, and Cancel/Resume preserves a partial download.

## Likely files

Android PresenceHud, SolarSystemVisual, CompanionModel, CompanionPackManager, LocalInferenceEngine, LlamaCppInferenceEngine, jarvis_llama.cpp and focused regression tests.

Follow-up: ModelDownloadState, ModelDownloadsUi, CompanionDeviceModelChrome, DevicePackChromePublisher, PhoneMemoryUi, DownloadedContentUi, MainActivity, and download lifecycle/Compose tests.

## Out of scope

Desktop inference, voice synthesis redesign, and changing phone tool permissions.

## Validation (2026-10-17)

- Android: 321 tests passed; debug APK assembled; both arm64-v8a and x86_64 native libraries compiled and present. Lint: zero errors, 48 warnings.
- Inspected rendered screenshots at 0%, 50%, and 100% context; sun, planets, rings and glow remain present as stars disappear.
- Full Python suite was attempted and interrupted after remaining at 20% in async database fixture setup; no backend source changed in this ticket. This is not a full backend test pass.
- No physical phone connected. Live Qwen 1.7B first-token timings, warm-cache speedup, motion on the handset, and installation remain unverified. Native logs report prompt/reused-token counts; app logs report queue, load, first-token and total milliseconds without prompt text.
- Prefix reuse helps successive phone-tool passes and opted-in warm follow-up replies. Existing 30-second warm-residency preference and pressure/background release behavior remain unchanged.

Follow-up: 327 Android tests pass, including immediate connecting feedback, cancellation while awaiting headers, partial-file resume with Range, visible retry recovery, checksum rejection, and UI Cancel/Resume behavior. Rendered the model library at phone dimensions and inspected the percentage, byte counts, transfer rate, model cards, and action targets. Debug APK and lint pass (zero errors, 49 warnings). Physical-phone timings remain unverified; no phone is attached through ADB.
