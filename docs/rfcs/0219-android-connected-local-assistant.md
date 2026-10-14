# RFC-0219: Android connected and local assistant

**Status:** accepted
**Author:** Daan via Codex
**Date:** 2026-10-13

## Problem
Phone setup needs a working off-network path, verified low-memory abliterated models,
consented phone tools, and system assistant activation.

## Decision
- Extends RFC-0215 remote pairing with the owner's explicit request for existing
  UPnP/manual forwarding. Tailscale remains the default for a remote toggle without a mode.
- Reuse owner-enabled UPnP/NAT-PMP/PCP on TCP 4781; mapping is not proof of cellular access.
- Add Tailscale as an explicit alternative, retaining pinned QR pairing and owner approval.
- Keep owner API 4780 and model ports private. Overlay peers cannot auto-enroll as LAN.
- Router administration requires ownership/change consent. A red model requires a separate
  approval tied to that router and setup task; ordinary setup never invokes it.
- Add pinned Qwen3 1.7B and 0.6B abliterated Q4_K_M packs and private GGUF import.
- PC remains default; owner can select local. Execute app tools through revocable per-app,
  per-category permissions, a confirmation queue, bounded steps, and stop control.
- Add Android voice interaction services and optional local Hey ANZU/Hey Anu keyword spotting.
  Existing STT/TTS is reused. Wake listening starts disabled.

## Acceptance criteria
- [ ] Remote QR and paired-phone connectivity evidence distinguish configuration from verification.
- [ ] Overlay endpoints work without router mapping and never weaken enrollment or TLS.
- [ ] No red-model invocation without independent explicit approval.
- [ ] Verified local packs load, use model chat templates, stream, and cancel.
- [ ] App tools enforce permission and screen freshness on local and PC requests.
- [ ] System assistant and wake service respect app lock and Android microphone restrictions.
- [ ] Backend tests, frontend build/lint, Android tests/build, APK native packaging checks pass.
- [ ] Physical S20-class and newer Samsung: cellular pairing, offline inference, tools, assistant,
  wake detection, battery/microphone checks. These remain unverified without devices.

## Likely files
Backend mobile connectivity, companion routes, tool registry; frontend phone pairing;
Android companion model, JNI, permissions, assistant services, settings; focused tests.

## Out of scope
Root access, exploits, public owner/model APIs, changing protected Architect specs,
automatic Tailscale account enrollment, and stable promotion to main.

## Implementation verification
- Current development fixes, remote opt-in migration, pairing deadlines, server
  proof, screenshot settings, local conversations, voice language, and download
  cancellation are preserved.
- Local Android unit tests: 292 passed. Debug/release builds passed; all existing
  native-runtime APK gates passed for arm64-v8a and x86_64, plus Sherpa and wake assets.
- Focused backend checks: 95 passed, with 28 connection/approval checks rerun after
  final integration. Windows runs use session event loops to avoid intermittent
  Windows socketpair stalls. Full-suite results are reported in the PR.
- Pinned 0.6B model generated multiple native token callbacks on Android emulator.
  The corrected wake model initializes on host CPU and rejects silence.
- Physical Samsung, cellular/router connectivity, audible wake activation, and
  on-device assistant/app-control acceptance remain unverified. No router on the
  owner's network was changed and no red-team model was invoked in development.
