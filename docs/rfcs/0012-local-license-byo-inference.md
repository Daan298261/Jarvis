# RFC-0012: Local license with BYO inference entitlement

**Status:** accepted  
**Queue item:** Licensing / local-first commercial model  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis needs a commercial model that does not require the vendor to host inference and remains usable on customer-owned hardware, including periods without internet connectivity.

## Decision

Treat the Jarvis orchestration platform entitlement separately from inference. Support customer-owned local/self-hosted inference and optional cloud providers while licensing Jarvis itself through cryptographically signed cluster entitlements/offline leases.

Entitlements govern product/pack features, not access to the customer's own local models or data. License validation must fail predictably without corrupting local state.

## Acceptance criteria

- [ ] Platform entitlement and model/provider credentials are separate concepts.
- [ ] Signed lease includes cluster identity, product tier/features, issue/expiry times, and offline grace policy.
- [ ] Offline validation requires no vendor network request during valid lease/grace.
- [ ] Reconnect handles time validation/tamper detection and lease refresh.
- [ ] Entitlement failure never deletes customer data/models.
- [ ] Specialist/Domain Pack entitlements can be evaluated cluster-wide.
- [ ] UI clearly distinguishes local inference cost from Jarvis subscription/licensing.
- [ ] Unit tests cover signature, expiry, grace, tamper, and cluster identity.

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
