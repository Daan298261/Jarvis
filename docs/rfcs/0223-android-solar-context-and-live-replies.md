# RFC-0223: Android solar context and live replies

**Status:** accepted

**Author:** Codex, requested by Daan

**Date:** 2026-10-17

## Problem

The phone orb resembles a solar system but lacks planets and context feedback. Local Qwen replies appear stalled because generated tokens are buffered until completion; phone tools can run ten silent inference passes.

## Decision

Extend orb mode with the eight planets, sun, rings, glow, thinking pulses and a seeded twinkling star field. Fade stars as the active phone model context fills, using native prompt and generated token counts; unknown context stays explicitly unknown. Preserve humanoid mode. Stream ordinary replies to Home and Chat, show elapsed work and tool stages, and record load/first-token/total latency. Reuse safe transformer prompt prefixes with a full-reset fallback for unsupported memory removal.

## Acceptance criteria

- Eight distinguishable planets orbit at independent, continuous speeds; Saturn has rings.
- Thinking visibly pulses sun and rings; reduced motion freezes movement and twinkling.
- Star visibility decreases monotonically with context use, restores on a new conversation, and has an accessible context label.
- Ordinary local output becomes visible before generation ends; internal tool JSON stays hidden.
- Stage progress and elapsed seconds remain visible during long loads, prefill and phone actions.
- Native prefix reuse resets on model changes and fails safely; logs distinguish first-token time from total time.
- Android tests, native compilation, APK assembly and lint pass. Physical phone speed remains a separate acceptance gate.

## Likely files

Android PresenceHud, SolarSystemVisual, CompanionModel, CompanionPackManager, LocalInferenceEngine, LlamaCppInferenceEngine, jarvis_llama.cpp and focused regression tests.

## Out of scope

Desktop inference, model downloads, voice synthesis redesign, and changing phone tool permissions.

## Validation (2026-10-17)

- Android: 321 tests passed; debug APK assembled; both arm64-v8a and x86_64 native libraries compiled and present. Lint: zero errors, 48 warnings.
- Inspected rendered screenshots at 0%, 50%, and 100% context; sun, planets, rings and glow remain present as stars disappear.
- Full Python suite was attempted and interrupted after remaining at 20% in async database fixture setup; no backend source changed in this ticket. This is not a full backend test pass.
- No physical phone connected. Live Qwen 1.7B first-token timings, warm-cache speedup, motion on the handset, and installation remain unverified. Native logs report prompt/reused-token counts; app logs report queue, load, first-token and total milliseconds without prompt text.
- Prefix reuse helps successive phone-tool passes and opted-in warm follow-up replies. Existing 30-second warm-residency preference and pressure/background release behavior remain unchanged.
