# RFC-0076: Companion APK delivery UX

**Status:** accepted
**Author:** Jarvis Architect
**Date:** 2026-09-11
**Owner for implement:** UX + D2 (companion build UI / send hooks) after this specs-only land

**Related (do not rewrite):** RFC-0059 companion delivery / provisioning; RFC-0063 6-digit pairing (install ≠ pair); RFC-0065 PC endpoint bring-up.

## Problem

On the 1.2.5 desktop test the owner cannot tell whether companion APK generation is running — no clear visual queue or progress. After a build there is no obvious **Download to Desktop** (current control is a generic “Download signed APK” browser save) and no send-via WhatsApp or email when those channels are already configured. Failures are easy to miss.

## Decision

Make APK generation a visible desktop job with a primary Desktop download and optional send when WhatsApp and/or email are configured. Align with RFC-0059 provisioning: personalized APKs carry only public server trust + invitation/code flow — no extra secrets.

### 1. Visible build queue

Desktop UI (`MobileCompanionSetup` / Phone companion card) shows explicit progress/state while generating the companion APK:

| State | Owner-visible |
| --- | --- |
| **Queued** | Waiting to start (position if a queue exists) |
| **Building** | In progress + last heartbeat / activity line (reuse existing `Build.state` / `activity` / `heartbeat_at`) |
| **Ready** | Completed; primary download enabled |
| **Failed** | Error text; retry affordance — never silent fail |

Do not leave the owner staring at a dead button with no status. If the builder is stale (`build.stale`), say so.

### 2. On ready — Download to Desktop

Primary action when ready: **Download to Desktop** (or save-as). Prefer the owner Desktop folder on Windows (`%USERPROFILE%\Desktop\Jarvis.apk` or `JarvisCompanion-<rev>.apk`); if the browser cannot write Desktop directly, use a clear save-as whose default filename is obvious. Existing `GET /api/mobile/manage/builds/{id}/apk` stays the bytes source.

### 3. Optional send — WhatsApp / email

If WhatsApp and/or email are configured (existing `GET /api/integrations` / `IntegrationSetup` / WhatsApp pairing + Gmail), offer:

- **Send APK via WhatsApp**
- **Email APK**

If a channel is **not** configured, show that control in a graceful **disabled** state with a short how-to (link to existing Setup “Connect Gmail and WhatsApp”) — never a silent no-op or a toast-less click.

Do **not** require WhatsApp or email to pair or to download. Pairing remains RFC-0063 / RFC-0074 (code + QR). Sending the APK is delivery convenience only.

Reuse existing send/MCP hooks where present; do not invent a second WhatsApp stack. Attachment size / provider limits must surface as a visible error with “Download to Desktop” still available.

### 4. Secrets / provisioning (RFC-0059)

Do not embed secrets in the APK beyond existing public trust + invitation/code flow. No owner private key, no pairing-code plaintext baked as the long-term secret, no repo-committed signing material. Regenerable 6-digit codes stay desktop-issued (RFC-0063 / RFC-0074).

### Will not

- Require WhatsApp or email to pair
- Ship secrets in the repo
- Redesign the full Android Gradle / signing pipeline (RFC-0059)
- Block RFC-0074 pairing on APK send

## Acceptance criteria

- [ ] Visual progress / queue during APK generation (queued / building / ready / failed + error)
- [ ] Download-to-Desktop (or equivalent save-as) when ready
- [ ] WhatsApp / email send affordances when configured; clear disabled + how-to when not — never silent fail
- [ ] Specs-only in this PR (no product code)
- [ ] Implement follow-up: `python3 -m pytest` if send/build APIs change; `npm --prefix frontend run build` when portal UI lands

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/pages/MobileCompanionSetup.tsx`, `frontend/src/pages/Phone.tsx`, `frontend/src/components/IntegrationSetup.tsx`, `frontend/src/api.ts` (build + integrations) |
| Backend | `backend/app/api/companion.py` (`POST /api/mobile/manage/builds`, `GET .../builds/{id}`, `GET .../apk`), `backend/app/api/integrations.py`, existing WhatsApp/email MCP send hooks |
| Tests | `tests/test_mobile_provision.py`, `tests/test_integration_setup.py`, UI/build-state tests |
| Docs | this RFC; optional Architect §59 line |

## Out of scope

Product implementation in this PR. Full Android build-pipeline redesign. Pairing QR / spoken onboarding (RFC-0074). Cloud-account stores. Committing APKs or signing keys.

## Notes

Taco 1.2.5 desktop test via CoS → Jarvis Architect (specs-only). Could not generate / see APK progress; wants Desktop download plus WhatsApp/email when configured.

RFC-0059 remains the provisioning/identity contract. This RFC is desktop delivery UX only.

Linux cloud VMs cannot sign off a live Windows Desktop save or WhatsApp send; those are owner-desktop verification after implement.
