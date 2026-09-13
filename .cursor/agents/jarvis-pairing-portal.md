---
name: jarvis-pairing-portal
description: Implements RFC-0074 companion pairing portal UX only. Use for Pair phone flows, QR, onboarding API, CompanionPairingPanel. Do not edit android/, backend/app/auth.py, or inference/hotswap files.
---

You implement **Stream A/E pairing (portal only)** from `docs/spec.md`.

**Own these paths only:**
- `frontend/src/components/CompanionPairingPanel.tsx`
- `frontend/src/pages/CompanionPairing.tsx`
- `frontend/src/pages/MobileCompanionSetup.tsx` (pairing/connection sections only)
- `frontend/src/pages/Settings.tsx` (pairing links only)
- `frontend/src/api.ts` (companion pairing + onboarding helpers only)
- `backend/app/api/mobile.py` or companion onboarding routes if present
- `backend/app/mobile/companion_onboarding.py`
- `tests/test_companion_pairing.py` (portal-related cases)

**Do not touch:** `android/**`, `backend/app/auth.py`, `backend/app/inference/**`, `frontend/src/hud/**`, `frontend/mobile-orb/**`.

**Done when:** Pair phone shows code+QR from server status; spoken onboarding offers wired via `fetchCompanionOnboarding`; tests pass for pairing.

Branch: `cursor/pairing-portal-1009` from latest `development`. One PR to `development`.
