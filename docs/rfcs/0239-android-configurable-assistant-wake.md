# RFC-0239: Configurable Android assistant and wake activation

**Status:** accepted
**Date:** 2026-10-25
**Author:** Codex, requested by Daan

## Problem
Assistant registration does not enable wake listening. Fixed phonemes cover only Hey ANZU/Anu. An activity alias makes settings routing dependent on OEM intent handling, and paused states are difficult to diagnose.

## Decision
Provide a real assistant preferences activity and recognition settings metadata, saved opt-in wake listening, configurable English phrases and pronunciation aliases (ANZU, Jarvis, Anoe, Enzo, Anzoo, Aanzo), a lower adjustable trigger threshold, clear pause status, and Samsung shortcut guidance. Use the existing local Sherpa model with validated phoneme tokens and packaged pronunciation dictionary. Resume saved listening only from foreground app lifecycle; do not start a microphone at boot. Preserve lock-screen pause and app access controls. Add optional screen-context consent. Fix capture and lifecycle conflicts in these paths.

## Acceptance criteria
System options resolve to ANZU preferences. Aliases compile to valid packaged tokens. Settings survive restart; invalid phrases receive validation errors. Threshold is bounded. Pauses release microphone and state their reason; user stop persists. Invocation reaches protected UI. Run Android tests/lint, signed APK native checks and physical tests when available. Unit tests alone do not prove spoken wake detection.

## Research
https://developer.android.com/reference/android/service/voice/VoiceInteractionService
https://www.samsung.com/us/support/answer/ANS10001575/
https://k2-fsa.github.io/sherpa/onnx/kws/index.html
