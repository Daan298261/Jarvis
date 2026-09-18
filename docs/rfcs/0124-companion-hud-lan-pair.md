# RFC-0124: Companion HUD render + LAN pair request

**Status:** implemented  
**Queue item:** (none — Taco product ask 2026-09-18; no new §58 checkbox)  
**Author:** Taco via implement session  
**Date:** 2026-09-18

**Related (do not rewrite):** [RFC-0059](0059-android-companion-delivery.md), [RFC-0063](0063-companion-six-digit-pairing-codes.md), [RFC-0074](0074-companion-pairing-streamline-and-qr.md), [RFC-0108](0108-phone-companion-offline-ai-model.md), [RFC-0123](0123-companion-reachability-and-anti-impersonation.md) (listen/auth/cooldown — sibling; this RFC does **not** implement impersonation cooldown).

## Problem

On the Android companion, the Home HUD WebView does not show the glowing orb or the particle humanoid (900px ApexOrb clipped, 0-size WebView, missing gitignored `assets/orb`, `shouldOverrideUrlLoading` swallowing the page). Home, Chat, and More repeat model/voice pickers and pairing chrome. The phone cannot find a Jarvis PC already on the same Wi‑Fi; owners must type endpoint + pin + 6-digit code.

## Decision

1. **HUD:** Render presence in Compose (glowing orb + point-cloud humanoid bust) driven by listening/thinking/speaking. Keep the WebView orb bundle as a non-blocking extra only if it actually paints; Compose is the source of truth so the HUD cannot be blank. Presence mode chips stay on More.
2. **Tabs:** Home is HUD + talk/pair. Chat is conversation + model/voice. More is connection, on-device models, presence, notifications, schedules. Do not repeat pickers or pairing forms across those tabs.
3. **LAN pair:** While the Leader is up, the TLS gateway advertises a short UDP beacon on **4782** (not a new companion API port; 4781 stays TLS). The phone scans the current Wi‑Fi, requests pairing immediately (`POST /api/companion/lan-enroll`), and waits. The PC must **approve the phone fingerprint** (existing confirm). 6-digit / QR remain the fallback. No pairing code in the beacon. LAN enroll is private-IP only and rate-limited. Session still 403 until confirm.

Default connectivity when no stored config exists: LAN listen on **4781** (`enabled=true`, `remote=false`) so a first-run desktop is discoverable. Stored owner configs are unchanged.

## Acceptance criteria

- [x] Home HUD shows a glowing orb and a particle humanoid (mode chip)
- [x] Duplicate model/voice/pairing chrome is not on every tab
- [x] Phone on the same Wi‑Fi discovers Jarvis and requests pair without typing endpoint/pin
- [x] Pairing stays pending until the owner approves the fingerprint on the PC
- [x] 6-digit / QR still work
- [x] `python3 -m pytest` for beacon parse, lan-enroll, private-IP gate, confirm-before-session
- [x] Android unit tests for HUD particles + beacon parse
- [ ] Physical phone soak is desktop sign-off

## Likely files

| Area | Paths |
| --- | --- |
| Android | `MainActivity.kt`, new `PresenceHud.kt`, `LanBeacon.kt`, `CompanionModel.kt`, `JarvisApi.kt`, `AndroidManifest.xml` |
| Backend | `backend/app/mobile/lan_beacon.py`, `identity.py`, `connectivity.py`, `gateway.py`, `api/companion.py` |
| Frontend | `CompanionPairingPanel.tsx` (pending LAN request copy) |
| Tests | `tests/test_rfc0124_lan_pair.py`, Android `LanBeaconTest`, `PresenceParticlesTest` |

## Out of scope

RFC-0123 impersonation cooldown / `detected-hack-attempt`. RFC-0108 pack download. WAN relay. Editing Architect spec docs.

## Notes

Taco 2026-09-18: HUD blank; duplicate tabs; scan current Wi‑Fi and ask for pairing immediately; PC approval; then merge to development and main.
