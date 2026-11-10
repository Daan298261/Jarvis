# RFC-0231: Android conversational voice and desktop projects

**Status:** accepted

**Author:** Codex, requested by Daan
**Date:** 2026-10-24

## Problem
The phone can remain listening indefinitely. Connected speech does not provide an immediate local acknowledgment, final spoken replies are inconsistent, and desktop project folders are inaccessible. The native presence differs from the humanoid showcase.

## Decision
Prefer phone partial speech recognition for conversational input, with a 250 ms post-speech silence endpoint and bounded no-speech/final-result waits. Retain PCM/desktop and installed Whisper fallbacks with the same endpoint. Submit to the desktop before starting a bounded phone-model acknowledgment; track the accepted task and speak its final output once. Expose the existing portal project store through authenticated companion routes and add a project browser and chat assignment. Package the existing humanoid WebGL renderer locally for the phone, retaining native rendering on WebGL failure.

## Acceptance criteria
- Live transcript appears while speaking; 250 ms of silence after speech ends capture, with no-input and overall deadlines.
- Cancellation, errors, final results and repeated mic taps release capture and clear listening.
- Desktop submission is independent of acknowledgment generation; late acknowledgments cannot overwrite final answers.
- A voice request's final desktop result is shown and spoken once.
- Existing desktop projects and chats can be opened on the phone; create, rename and move use the shared desktop store, and cached browsing works disconnected.
- Humanoid mode uses the existing showcase geometry and motion, with reduced motion and native fallback.
- Targeted backend and Android tests, frontend build/lint, APK assembly and native-library checks pass. Physical-phone timing and visual acceptance remain explicitly separate.

## Likely files
Android voice, CompanionModel, project UI, local presence WebView; frontend mobile presence entry/build; backend companion project routes and conversation serialization; regression tests.

## Out of scope
New swarm orchestration, unrelated desktop UI changes, stable release promotion.
