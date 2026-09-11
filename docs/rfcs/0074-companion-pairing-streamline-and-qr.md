# RFC-0074: Companion pairing streamlining + QR + spoken onboarding

**Status:** accepted
**Author:** Jarvis Architect
**Date:** 2026-09-11
**Owner for implement:** UX + D1 (desktop pair UI / companion enroll) after this specs-only land

**Related (do not rewrite):** RFC-0059 companion delivery / identity; RFC-0063 regenerable 6-digit pairing codes; RFC-0065 PC endpoint bring-up; RFC-0067 hide chrome + conversational greeting; RFC-0049 conversational onboarding.

## Problem

After the 1.2.5 desktop test, owner pairing fails. When no owner private key is set, the pair path blocks instead of minting identity and continuing. Setup is not a single owner path: no QR on the pair screen, the 6-digit code (RFC-0063) is not enough on its own, and the Jarvis-side companion enroll / pair endpoint appears broken (`403 Owner private key is not configured` on `/api/mobile/manage/pairing-codes*` when the key is unset; frontend `getActiveCompanionPairingCode` also never hits `GET /api/mobile/manage/pairing-codes/status` and only returns an in-memory cache). There is no spoken walkthrough offering pair-phone vs explore-features.

## Decision

Streamline owner pairing so “Pair phone” always produces a working session, shows both a 6-digit code and a QR for the same payload, and can be walked through by voice. Do not redesign Android Keystore identity or the full companion stack.

### 1. Auto key material on pair intent

If pairing identity / the owner private key is unset when the owner starts **Pair phone**, mint it automatically (reuse `backend/app/auth.py` `generate_private_key` / existing persist path). Persist securely; never log the secret; store in the same owner-key slot Settings already uses. Do not require a manual Settings key ceremony before pairing.

Phone-side device identity stays RFC-0059 Android Keystore. This RFC only auto-creates the **desktop owner** key that currently gates `owner_router` (`require_owner_private_key` on `/api/mobile/manage`).

### 2. Streamlined pair UX (single owner path)

One path:

1. Owner opens Pair phone (portal `/companion-pairing`, Settings compact panel, or Phone setup).
2. Key is ready (auto-mint if needed).
3. Desktop shows a **regenerable 6-digit code (RFC-0063)** and a **QR** encoding the same enroll payload / deep link (code + LAN/TLS endpoint + server pin as already prepared by RFC-0065 / “Prepare connection”).
4. Phone scans the QR or types the 6 digits (`CompanionCodeValidator` / `MainActivity` pair screen).
5. Owner confirms the phone fingerprint.

Fix the broken Jarvis-side companion enroll / pair surface so that path is green. Likely fail points to name or fix in the implement PR:

| Surface | Path | Observed / likely failure |
| --- | --- | --- |
| Owner pair mint | `POST /api/mobile/manage/pairing-codes` (+ regenerate / status) | `403` when owner key unset; management router requires `require_owner_private_key` |
| Owner pair status | `GET /api/mobile/manage/pairing-codes/status` | Frontend cache in `getActiveCompanionPairingCode` never calls it |
| Phone enroll | `POST /api/companion/enroll` | Phone-side; auth-exempt today — verify still works after key auto-mint and RFC-0065 endpoint bring-up |

Green path after this RFC: unset key → Pair phone → `200` code + QR → phone enroll → owner confirm. Document the failing API + green path in the implement PR if a remaining 1.2.5 break is not the key gate.

### 3. QR on desktop

Large, scannable QR on the pair screen (full `CompanionPairingPanel`, not only compact). Same session as the 6-digit display: TTL countdown, **Regenerate** (invalidates prior unclaimed code per RFC-0063), optional copy. QR payload is the enroll deep link / same code+endpoint+pin — not a second secret.

### 4. Spoken onboarding

On first-run, or when the owner asks to connect a phone (and optionally to explore), Jarvis **speaks** short butler steps (RFC-0061 pack / RFC-0067 greeting — not a PLAN dump):

- (a) pair phone — walk the path in §2 (open pair, show code+QR, wait for confirm);
- (b) explore other features — hand off to existing conversational onboarding (RFC-0049) without setup-wizard chrome.

Align greeting/TTS gates with RFC-0067 (`speak_chat_replies`, mute/DND). Do not dump PLAN / END STATE / ACCEPTANCE.

### Will not

- Redesign Android Keystore identity (RFC-0059)
- Rewrite the full companion / mobile gateway / relay stack
- Require cloud accounts for local LAN pair
- Bake long invitation strings back as the primary UX (RFC-0063 remains 6-digit)

## Acceptance criteria

- [ ] Pairing works end-to-end when no prior owner key exists (auto-create on pair intent; secrets never logged)
- [ ] Desktop shows a regenerable 6-digit code **and** a QR for the same pairing session
- [ ] Broken pair/enroll endpoint fixed, **or** the implement PR names the failing API and the green path
- [ ] Spoken offer: pair phone vs explore features; walkthrough without plan chrome
- [ ] Specs-only in this PR (no product code)
- [ ] Implement follow-up: `python3 -m pytest` (pairing tests); `npm --prefix frontend run build` if portal touched

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/components/CompanionPairingPanel.tsx`, `frontend/src/pages/CompanionPairing.tsx`, `frontend/src/pages/MobileCompanionSetup.tsx`, `frontend/src/api.ts` (`getActiveCompanionPairingCode` / create / regenerate) |
| Backend | `backend/app/api/companion.py` (`/api/companion/enroll`, `/api/mobile/manage/pairing-codes*`), `backend/app/auth.py` (`generate_private_key`, `require_owner_private_key`), `backend/app/mobile/identity.py` |
| Android | `android/app/src/main/java/com/jarvis/companion/MainActivity.kt` pair screen, `JarvisApi.kt` enroll, `CompanionCodeValidator.kt` |
| Tests | `tests/test_companion_pairing.py`, `tests/test_mobile_companion.py` |
| Docs | this RFC; optional Architect §59 line |

## Out of scope

Product implementation in this PR. RFC-0059 Keystore / APK identity model. Full companion rewrite. Public Firebase relay. RFC-0076 APK download / WhatsApp-email delivery (separate). Cloud-account pairing.

## Notes

Taco 1.2.5 desktop test via CoS → Jarvis Architect (specs-only). Pairing failed; missing private key blocked the flow; no QR; Jarvis-side endpoint appeared broken; no spoken walkthrough.

RFC-0059 / 0063 / 0065 / 0067 / 0049 stay authoritative. This RFC owns auto-mint + QR + spoken pair-vs-explore walkthrough and the broken enroll/pair green path.

Linux cloud VMs cannot sign off physical-phone pair; desktop + phone soak remains owner sign-off.
