# RFC-0220: Usable Android controls and settings

**Status:** accepted
**Author:** Daan via Codex
**Date:** 2026-10-14

## Problem
Studio is a placeholder occupying a main navigation tab. More is a long wall of
controls, and stale desktop tasks/schedules still offer actions when disconnected.
Manual pairing fields distract from the working QR setup.

## Decision
- Remove the Studio navigation entry until a real generation UI/runtime exists.
- Keep tasks visible when connected or when cached tasks can be read; disable
  desktop mutations while disconnected and explain the needed connection.
- Group More into compact expandable settings cards. Keep model setup easy to find,
  preserve entered values, and put raw pairing fields behind manual setup.
- Make QR scanning the primary pairing action and preserve approval/fingerprint checks.
- Retain detailed persona/presence artwork and existing offline voice/content features.

## Acceptance criteria
- [ ] No placeholder image/video generation destination in primary navigation.
- [ ] Offline cached tasks/schedules are readable but cannot invoke desktop mutations.
- [ ] Settings are grouped, labeled, expandable, and keep model/pairing access obvious.
- [ ] Incomplete manual connection details cannot trigger a pairing request.
- [ ] Android tests/build and APK native packaging verification pass.

## Notes
Qwen-Image 2.1 Turbo is an image diffusion model, not a phone chat GGUF. The current
APK has llama.cpp and voice runtimes, no image diffusion runtime. A phone deployment
needs a separate runtime and RAM/performance benchmarks; this ticket does not present
untested image generation as an available feature.
