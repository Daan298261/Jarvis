# RFC-0177: Shared dot-persona motion cues

**Status:** implemented
**Implemented:** #429 @ `f0ea9e40bb186971bf75119bb966462da900a9da` (breath, listen shimmer, phase energy, real-TTS speech response, transient alert impulse). Status line also set by #433 @ `a128942e7849cec9ceeb8eabb04e70d4b44dcd83`.
**Specs:** #426 @ `d792ed4749bfc5857e8f1a55435b2b4d99714d28`.
**Quality bar:** **Anzu 1.0**. Full intent. No stubs / soft-fail.
**Residuals:** none. #429 lists no residual. Acceptance rows are checked. Reduced-motion stays static. RFC-0175 lifecycle behavior stays.
**Author:** Codex
**Date:** 2026-09-25

**Depends on:** [RFC-0176](0176-shared-dot-appearance-profiles.md)
**Related (do not rewrite):** [RFC-0050](0050-ui-v3-presence-architecture.md) (canonical presence state and attention); [RFC-0051](0051-humanoid-presence-runtime.md) (reduced motion); [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (`uMorph`); [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (persona identity); [RFC-0175](0175-galaxy-presence-option-chat-waveform-and-advanced-controls.md) (outer idle/engaged lifecycle).

### Quality bar

The implement is **multibillion-company grade** and the user-facing stretch is **Anzu 1.0**. Cues run on the existing snapshot and the live TTS analyser. A second phase machine, a synthetic speech meter, or cues that only run on one persona shape is a **fail**. Full intent. No stubs / soft-fail.

## Problem

The APEX humanoid materials describe assembly, breathing, distinct moods, depth-aware head turns, a living backdrop, and shockwave effects. Jarvis already has shared presence phases and shared dot shaders, but new motion cues should be authored once and applied across all persona shapes. Implementing these effects inside individual shapes would make quality inconsistent and multiply maintenance.

## Decision

Add a shared motion-cue layer to the dot engine. It maps existing `PresenceSnapshot` values, real audio level, and the existing attention vector into reusable cues: idle breathing, listening response, thinking/executing energy, real-audio speech response, and a short alert impulse. Named persona appearance profiles may tune cue intensity and color within bounded ranges; they do not define another phase machine.

The RFC-0175 idle / engaged transition remains the outer lifecycle and retains ownership of `uMorph`, pointer / face attract, reduced-motion behavior, and phase grouping. This RFC adds cues within those stages; it must not add a second canvas, morph uniform, webcam stack, synthetic audio meter, or TTS/AI logic. Effects and artwork are original Jarvis work, not copied APEX source.

## Acceptance criteria

- [x] The shared engine exposes a bounded, typed cue set for breath, listen, think/work, speech, and alert, driven by the existing snapshot and attention/audio inputs.
- [x] Every registered persona shape receives the same cue implementation; its profile can tune intensity without shape-specific renderer code.
- [x] Speech response follows the attached live TTS analyser only while real speech is active; it is quiet when idle, when listening, or when audio data is absent. A snapshot scalar alone must not fabricate speech activity.
- [x] Cue transitions are smoothed and interrupt safely when the presence phase changes.
- [x] Reduced motion removes continuous breathing and traveling impulses while preserving a clear static phase indication; attention chase follows RFC-0175's existing reduced-motion contract.
- [x] The preview harness can drive each cue over every persona shape and inspect its reduced-motion behavior without a live model or webcam.
- [x] RFC-0175's free-cloud / figure morph and camera privacy/fallback acceptance remain unchanged and independently testable.

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/presence/presenceState.ts`, `presenceTypes.ts`, `renderers/morphableOrbCloud.ts`, shared dot renderer, persona appearance profiles, `frontend/presence-check.tsx` |
| Tests | Presence phase mapping, cue timing, audio-level gating, and reduced-motion tests |

## Out of scope

New persona rows, persona-specific renderers, a new phase/state machine, webcam acquisition or storage, fabricated speech activity, changing RFC-0175 morph/attract behavior, assistant intelligence, and voice-engine work.

## Notes

The APEX source kit documents these visual effect categories but excludes APEX's assistant and voice. Jarvis should implement original cues that respond to its own truthful runtime state.

Product landed on development via #429 @ `f0ea9e40bb186971bf75119bb966462da900a9da`. Specs were #426 @ `d792ed4749bfc5857e8f1a55435b2b4d99714d28`. Quality bar stays **Anzu 1.0**. No residual.
