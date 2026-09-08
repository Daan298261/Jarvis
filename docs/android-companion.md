# Android companion — RFC-0059

The native app lives in `android/`. Keep work on `cursor/android-companion-99ea`
until the remaining release checks below are complete. This is an implementation
preview, not a production remote-access release.

## Implemented

- Kotlin/Compose Home, Chat, Tasks, Studio capability notice, and More screens.
- The same vendored Apex orb as desktop, bundled locally with no credential bridge.
- P-256 Android Keystore device identity, owner-confirmed pairing, short sessions,
  per-device revocation, and pinned TLS server identity.
- Native API integration for task/model control, conversation history, file sharing,
  attachments, STT/TTS, and persistent once/daily/weekly schedules.
- Device-authenticated, allowlisted TLS gateway; owner/desktop APIs are not forwarded.
- WebRTC voice bridge, call signaling, Android Telecom integration and optional FCM
  wake adapter. Calls require additional runtime dependencies and device validation.

## Build

Prerequisites: JDK 17, Android SDK platform 35, Node.js, Python backend dependencies.
Set `JAVA_HOME` and `ANDROID_HOME` for your installation. Android dependencies are
pinned in Gradle; `gradlew` downloads Gradle 8.9.

```powershell
npm --prefix frontend ci
Push-Location frontend
npm exec -- vite build --config vite.orb.config.ts
Pop-Location
Push-Location android
.\gradlew.bat :app:assembleDebug :app:lintDebug
Pop-Location
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`. A debug APK is for
development. Production personalization must use a persistent release keystore.
Public connection settings may be supplied through an ignored `android/bootstrap.json`:

```json
{"endpoint":"https://your-jarvis-host:4781","server_pin":"64 hexadecimal SHA256 SPKI characters","invitation":"temporary invitation"}
```

There are no permanent swarm credentials in this file. Keep even temporary
invitations out of Git. On the phone, use More to enter settings if not bundled.

## Connect

Start the normal Jarvis backend on localhost. Start the separate TLS ingress:

```powershell
$env:PYTHONPATH = 'backend'
python -m app.mobile.gateway --host YOUR_LAN_IP --port 4781
```

The gateway prints its public server fingerprint. Its server key stays in ignored
`data/mobile/tls/`; renewing the certificate retains the key and pin. Supply every
DNS name/IP the phone will use through repeated `--host` arguments. Never expose
the ordinary HTTP backend or inference port to WAN.

Owner management APIs require the existing owner key even on localhost:

- `POST /api/mobile/manage/invitations`
- `GET /api/mobile/manage/devices`
- `POST /api/mobile/manage/devices/{id}/confirm` with the phone's `fingerprint`
- `POST /api/mobile/manage/devices/{id}/revoke`

Pairing creates a pending record; copying an invitation cannot authorize another
phone after it has been claimed. Confirm the fingerprint on the desktop and press
Connect on the phone. A revoked device must pair again.

## Voice and push

Install `backend/requirements-mobile.txt`. STT/TTS reuse installed Jarvis voice
providers; this does not download model weights. Configure TURN using
`JARVIS_TURN_URL` and `JARVIS_TURN_SECRET` (coturn REST shared-secret authentication).
Push configuration uses `JARVIS_PUSH_URL` and `JARVIS_PUSH_CREDENTIAL`; the adapter
sends only destination registration token, opaque event ID and event kind. A real
FCM project and compatible push service are required. No public infrastructure is
deployed by this branch yet.

## Verification (2026-09-09)

- Android debug APK: built successfully.
- Android lint: passes; warnings include older pinned libraries and intentional
  Keystore/pinned-TLS/locally bundled WebView usage.
- `tests/test_mobile_companion.py`: 9 passing tests (pairing, replay, copied invite,
  revocation, localhost authentication, attachment ownership, TLS identity, gateway
  isolation and schedule DST/missed-run handling).
- Broader pytest attempt: 109 passed before stopping at 5 failures. All 5 failures
  reproduced on untouched base `146adab`: shell benchmark missing `sh`, best-of-N
  fixture output missing, two Cursor installation assumptions, and a Linux-only
  Office expectation on Windows. The complete backend suite is not green.

## Remaining release acceptance

- Full router automation and automatic hosted relay provisioning; public push deployment.
- Installer-integrated personalized release APK build/signing and secure downloads.
- Physical-phone incoming/background calls, audio routes, interruptions, reconnection,
  process recreation, foreground-service/permission behavior and device battery tests.
- Durable mobile outbox/recovery, complete coding approvals, schedule editing and
  generation artifact integration. Studio clearly reports BlackGrid as disconnected.
- Live-model and multi-node execution verification. The phone is a controller;
  this branch does not implement new swarm consensus or phone-side inference.
