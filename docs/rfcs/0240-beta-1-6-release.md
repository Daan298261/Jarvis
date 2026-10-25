# RFC-0240: ANZU 1.6 beta release

**Status:** accepted
**Date:** 2026-10-25
**Author:** Codex, requested by Daan

## Decision
After the requested desktop and Android fixes pass checks and merge into development, align all product version sources to 1.6.0-beta, the next minor beta after 1.5.3-beta. Keep the testing-team release a prerelease; do not promote main. Validate version coherence, frontend build/lint, Android tests/native packaging, and desktop compilation. Publish the prerelease tag from the tested development commit and dispatch Android CI plus the established Windows/Android release build. Report physical-phone testing as omitted at the owner's request, and distinguish started builds from completed deliverables.

## Scope
Version metadata, release notes, coherence checks and final QA regressions in the requested behavior. Final QA includes clearing the wake cooldown status when the service stops, and making the original missing Windows cuBLAS fix durable: preflight Whisper CUDA dependencies and use CPU/int8 when unavailable. Prerequisites: RFC-0231 speech fallback, RFC-0237 avatars, RFC-0238 Obsidian, RFC-0239 assistant settings. No unrelated PR merges, model-stack changes or architect specification edits.
