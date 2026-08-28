# RFC-0012: Local license with BYO inference entitlement

**Status:** implemented  
**Queue item:** Licensing / local-first commercial model  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis needs a commercial model that does not require the vendor to host inference and remains usable on customer-owned hardware, including periods without internet connectivity.

## Decision

Treat the Jarvis orchestration platform entitlement separately from inference. Support customer-owned local/self-hosted inference and optional cloud providers while licensing Jarvis itself through cryptographically signed cluster entitlements/offline leases.

Entitlements govern product/pack features, not access to the customer's own local models or data. License validation must fail predictably without corrupting local state.

## Acceptance criteria

- [x] Platform entitlement and model/provider credentials are separate concepts.
- [x] Signed lease includes cluster identity, product tier/features, issue/expiry times, and offline grace policy.
- [x] Offline validation requires no vendor network request during valid lease/grace.
- [x] Reconnect handles time validation/tamper detection and lease refresh.
- [x] Entitlement failure never deletes customer data/models.
- [x] Specialist/Domain Pack entitlements can be evaluated cluster-wide.
- [x] UI clearly distinguishes local inference cost from Jarvis subscription/licensing.
- [x] Unit tests cover signature, expiry, grace, tamper, and cluster identity.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | licensing/entitlement service, cluster identity |
| Frontend | license status/settings |
| Tests | entitlement crypto/state tests |
| Docs | licensing architecture |

## Out of scope

Final pricing levels, payment processor integration, DRM of customer-owned models.

## Notes

Inspiration: Zoey BYO Architect/local license direction. Recommendation: ADAPT.

Landed on `cursor/local-qwen-desktop-agent`: backend PR #66 (`7b44ebe`) — license entitlement only, not a `RemoteOpenAICompatibleBackend` rewrite; portal UI PR #82 (`93e0555`).
