# RFC-0213: Android pairing and app access

**Status:** accepted
**Author:** Codex, owner request
**Date:** 2026-10-10

## Problem

The desktop can mint a pairing code without preparing a usable QR endpoint. First-run pairing should work before a phone is detected. The phone also needs optional access protection for its conversations and security features.

## Decision

- Opening Pair phone or regenerating its code requests LAN TLS preparation automatically. No detected or enrolled device is required. Existing WAN settings remain intact; pairing does not create a WAN mapping. Security cooldowns still block preparation.
- Show one QR containing the existing HTTPS endpoint, certificate fingerprint, and expiring six-digit code. Keep fingerprint approval and device sessions unchanged. The Android Home and More scanners support QR and Wi-Fi discovery.
- More → App access lets the owner require the Android screen-lock PIN/password or strong biometrics. Enabling and disabling require system authentication. Android 10 uses device credentials; Android 11+ also supports strong biometrics. Do not store an app-specific PIN or biometric data.
- Gate all app screens before processing incoming share intents. Start locked on process/activity creation and lock when backgrounded. Block screenshots and recents capture while protection is enabled.

## Acceptance

- With no enrolled devices and no prepared connection, pair intent produces a scannable invitation on a LAN-connected desktop.
- Failed preparation does not issue a new code. Regeneration invalidates the previous invitation.
- WAN mapping and security cooldown behavior remain intact.
- Native Android authentication gates opening the app and changing protection.
- Backend pairing tests, frontend build/lint, and Android build/lint/unit tests pass.
- Physical-phone scanning, biometrics, PIN fallback, background return, and offline voice remain device acceptance checks.

## Files

`backend/app/mobile/connectivity.py`, `backend/app/api/companion.py`, frontend pairing API/panel, Android activity/access lock/manifest/Gradle, focused tests.
