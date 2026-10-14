# RFC-0215: Android connected and local assistant

**Status:** accepted
**Author:** Daan via Codex
**Date:** 2026-10-13

## Problem
Phone setup needs a working off-network path, verified low-memory abliterated models,
consented phone tools, and system assistant activation.

## Decision
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

## Recovery integration

Recover the on-device assistant, opt-in accessibility tools, wake service, and authenticated phone tool/result endpoints against current development. Current pairing/network controls are retained; the older setup UI targeted a superseded connectivity API and is not reintroduced. Physical-phone and cellular acceptance remains separate.
