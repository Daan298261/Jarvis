# RFC-0059: Android companion delivery

**Status:** accepted  
**Author:** Codex, at the owner's request  
**Date:** 2026-09-08

## Problem

The Phone PWA cannot provide secure independent device identity, APK provisioning,
native incoming calls, or complete mobile supervision. RFC-0039 establishes the
native direction; the owner has now explicitly requested its implementation.

## Decision

Implement the approved Android companion in this repository, isolated from the
desktop checkout. This named delivery ticket includes mobile backend services,
native Kotlin/Compose screens, the existing Apex orb, signing/provisioning tools,
TLS connectivity, schedules, attachments, voice and call adapters, and tests.
Reuse the existing task executor, policy, models, events, coding and conversations.
Device identity is generated in Android Keystore; the personalized APK contains
only public server trust and an expiring invitation. Owner confirmation binds it.
Mobile gateways authenticate every request even when desktop localhost auth is off.
Direct access is preferred; optional public relay and push infrastructure belongs
to this project. Deployments require operator configuration, never embedded secrets.

## Acceptance criteria

- [ ] Installable Android APK with Apex home, chat, task/model control and settings.
- [ ] Owner-confirmed device enrollment, proof of key possession, revocation and TLS.
- [ ] Persistent conversations, attachments and restart-safe schedules.
- [ ] STT/TTS and native calls with authenticated signaling and push adapter.
- [ ] Provisioning creates signed APKs without changing signing identity on update.
- [ ] Direct/relay transport reports verified connectivity or actionable limitations.
- [ ] Security, idempotency and schedule tests; backend suite; Android build and lint.
- [ ] Real-device incoming calls and live-model acceptance recorded separately.

## Boundaries

BlackGrid generation/stitching is a later integration. Include its capability and
artifact contract now, never advertise a placeholder as an operational generator.
The phone is a controller, not a compute worker. No carrier calling or new swarm
consensus algorithm. Preserve architect-owned specification documents.

## Delivery record

See `docs/android-companion.md` for exact build/setup instructions and verified
versus externally dependent features. No existing production installation is
reconfigured by building or testing this worktree.
