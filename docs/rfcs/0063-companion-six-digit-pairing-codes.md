# RFC-0063: Regenerable 6-digit Android companion pairing codes

**Status:** accepted

**Queue item:** P1 — Companion pairing UX (blocks comfortable #132 land)

**Author:** Jarvis Architect

**Date:** 2026-09-10

## Problem

Companion pairing today uses a long `token_urlsafe(32)` invitation string baked into APKs / shown in the portal. That is hard to read aloud, hard to type on a phone, and regeneration is not a first-class “new code” flow. Taco wants a **small regenerable code** verified via the Jarvis endpoint.

## Decision

Replace (or dual-support then migrate) long invitation tokens with **6-digit decimal pairing codes** for owner↔phone enrollment.

### Code properties

- Format: exactly 6 digits (`000000`–`999999`), displayed zero-padded.
- Entropy: generate with CSPRNG; reject trivial codes optionally (`000000`, `123456`) or accept all — prefer reject obvious sequences.
- TTL: default 10 minutes (owner-configurable 5–60); single-use until claimed or expired.
- **Regenerate:** owner can mint a new code anytime; previous unclaimed codes for that pairing session are invalidated (latest-wins per owner).
- Storage: store only a keyed hash of the code (or HMAC with server secret), never log plaintext codes; show plaintext only in owner UI once at creation.
- Rate limit: enroll attempts per IP/device fingerprint (e.g. 5/15min) to blunt guessing (~1e6 space).

### Verify via endpoint

Phone (or existing APK) submits `{ code, public_key, name }` to companion enroll API over the TLS mobile gateway. Server validates code hash + TTL + unclaimed, then same pending-device + owner fingerprint confirm flow as RFC-0059.

### APK bootstrap

Personalized APKs may omit a baked invitation; prefer: bake endpoints + server_pin only, then user enters 6-digit code from desktop “Pair phone” UI after Prepare connection. If a code is baked for first-run convenience, it must still be regenerable from desktop (new code invalidates baked one).

### UI

- Desktop: big 6-digit display, countdown TTL, **Regenerate code** button, copy optional.
- Android: numeric keypad entry for 6 digits; clear error on expire/invalid.

### Compatibility

During transition, accept legacy long invitations if still unexpired; new UI only issues 6-digit codes. Document deprecation.

## Acceptance criteria

- [ ] Owner can generate and regenerate 6-digit codes; regenerate invalidates prior unclaimed code
- [ ] Enroll via HTTPS companion endpoint with code + device public key
- [ ] Codes hashed at rest; rate-limited verify; TTL enforced
- [ ] Portal shows code + regenerate; Android entry UI
- [ ] APK bootstrap works without long invitation string
- [ ] Unit tests for generate/regenerate/expire/claim/rate-limit
- [ ] `python3 -m pytest` (+ Android unit tests if UI touched)

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/mobile/identity.py`, companion API |
| Frontend | `frontend/src/.../MobileCompanionSetup.tsx` |
| Android | pairing/enroll screen |
| Tests | identity/pairing tests |

## Out of scope

Public Firebase relay completion; full RFC-0059 device soak; merging #132 before remaining land-bar items.

## Notes

Related: RFC-0059 / PR #132.

Taco 2026-09-10: do not merge #132 until open companion tasks done; pairing must be regenerable 6-digit via endpoint.
