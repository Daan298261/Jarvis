# Android companion — RFC-0059

**MVP LAN pairing (step-by-step):** [`ANDROID_MVP_LAN_CHECKLIST.md`](ANDROID_MVP_LAN_CHECKLIST.md) — preferred `JarvisCompanion-a1be0f1.apk` (1.2.0), `192.168.x.x:4781`, six-digit code, smoke tests, emulator vs phone gaps.

The native app lives in `android/`. Keep work on `cursor/android-companion-99ea`
until the remaining release checks below are complete. This is an implementation
preview, not a production remote-access release.

## Implemented

- Kotlin/Compose Home, Chat, Tasks, Studio capability notice, and More screens.
- The same vendored Apex orb as desktop, bundled locally with no credential bridge.
- Selectable glowing-orb and efficient WebGL humanoid HUD modes, both driven by
  listening/thinking/speaking state and bundled entirely inside the APK.
- P-256 Android Keystore device identity, owner-confirmed pairing, short sessions,
  per-device revocation, and pinned TLS server identity.
- Native API integration for task/model control, conversation history, file sharing,
  attachments and direct camera capture, STT/TTS, and editable persistent
  once/daily/weekly schedules.
- Duplex realtime voice over authenticated WSS (`/api/companion/voice/realtime`): partial
  transcripts, sentence-level TTS playback before full completion, replay-safe sequences,
  per-device rate limits, and profile-routed host TTS. Clip HTTPS STT/TTS remains fallback.
- Mobile TTS uses the PC voice-profile catalog with an in-app selector and preview.
  Recorded STT and generated speech use device-authenticated pinned TLS; no speech
  model or permanent Jarvis credential is stored on the phone.
- Device-authenticated, allowlisted TLS gateway; owner/desktop APIs are not forwarded.
- WebRTC voice bridge, call signaling, Android Telecom integration and optional FCM
  wake adapter. Failed media reconnects use ordered, replay-safe offer generations.
  Calls require additional runtime dependencies and physical-device validation.
- Push events use a durable local retry queue with bounded backoff, preference and
  revocation checks, call expiry, and per-state task deduplication.
- Exact-action, expiring task approvals with protection against stale/replayed dialogs.
- The Tasks screen projects current swarm node/worker liveness and coding-worker
  availability, and lets an authenticated companion resolve coding decision-inbox items.
- Encrypted pending-message recovery with stable request IDs, foreground-only polling,
  incoming intent handling, call mute/audio-route controls and queued voice follow-ups.
- Desktop owner pairing/build controls and a personalized release APK builder with a
  persistent signing identity, live heartbeats and interrupted-build recovery.
  Relay/push service source lives in `services/mobile-relay/`.
- Owner-started TLS gateway lifecycle with verified local authentication, one-hour
  UPnP leases that preserve foreign mappings, and multi-endpoint Android fallback.
- Regenerable six-digit pairing codes are HMAC-protected at rest, expire after ten
  minutes, are rate limited, and still require exact fingerprint confirmation.

## Build

Prerequisites: JDK 17, Android SDK platform 35, Node.js, Python backend dependencies.
The APK builder auto-discovers Eclipse Temurin / Microsoft JDK 17 and the
Jarvis Android SDK (`%LOCALAPPDATA%\Jarvis\android-sdk`) when `JAVA_HOME` /
`ANDROID_HOME` are unset. Android dependencies are pinned in Gradle; `gradlew`
downloads Gradle 8.9.

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

Owner management APIs require the existing owner key even on localhost. In the
desktop Android companion panel, select **Prepare connection** before building:

- Jarvis starts and probes the restricted TLS gateway itself.
- Local Wi-Fi endpoints are added to the APK automatically.
- Optional router discovery requests a one-hour lease only after the gateway proves
  that device authentication is enforced. Existing foreign mappings are preserved.
- A router lease is reported separately from verified internet reachability. Configure
  `JARVIS_RELAY_ENDPOINT`, `JARVIS_RELAY_URL`, and `JARVIS_RELAY_CREDENTIAL` for the
  hosted fallback after deploying `services/mobile-relay/`.

Relevant owner APIs:

- `POST /api/mobile/manage/invitations`
- `POST /api/mobile/manage/pairing-codes` (preferred; six digits, ten minutes)
- `POST /api/mobile/manage/pairing-codes/regenerate`
- `GET|POST /api/mobile/manage/connection`
- `GET /api/mobile/manage/devices`
- `POST /api/mobile/manage/devices/{id}/confirm` with the phone's `fingerprint`
- `POST /api/mobile/manage/devices/{id}/revoke`

Pairing creates a pending record. New apps use the six-digit desktop code; legacy
long invitations remain accepted until their expiry. Confirm the fingerprint on the
same desktop pairing screen and press Connect on the phone. A revoked device must
pair again.

## Voice and push

Install `backend/requirements-mobile.txt`. STT/TTS reuse installed Jarvis voice
providers; this does not download model weights.

### Operator environment templates

- Relay host: copy `services/mobile-relay/.env.example` to `.env` on the public
  Linux machine (never commit secrets). See `services/mobile-relay/README.md`.
- Jarvis desktop: copy `docs/examples/mobile-companion.env.example` and set values
  in your OS or service environment.

| Variable | Role |
| --- | --- |
| `JARVIS_RELAY_URL` / `JARVIS_RELAY_CREDENTIAL` | Outbound relay agent (Jarvis → relay) |
| `JARVIS_RELAY_ENDPOINT` | Phone HTTPS fallback origin after relay registration |
| `JARVIS_PUSH_URL` / `JARVIS_PUSH_CREDENTIAL` | Opaque FCM broker on the relay |
| `JARVIS_TURN_URL` / `JARVIS_TURN_SECRET` | coturn REST shared-secret ICE |
| `JARVIS_FIREBASE_CLIENT_CONFIG` | Path to **public** Android client JSON for APK builds |

Owner API `GET /api/mobile/manage/infrastructure` returns booleans only for whether
each piece is configured (no credentials echoed). Device call capabilities mirror
push/TURN readiness for the companion UI.

Configure TURN using `JARVIS_TURN_URL` and `JARVIS_TURN_SECRET` (coturn REST
shared-secret authentication). Push configuration uses `JARVIS_PUSH_URL` and
`JARVIS_PUSH_CREDENTIAL`; the adapter sends only destination registration token,
opaque event ID and event kind. A real FCM project and compatible push service are
required.

### Operator checklist (remote voice and background calls)

1. **Firebase** — Create a Firebase project. Download the **service account JSON**
   for the relay host only (`FIREBASE_CREDENTIAL_FILE`). Download the **Android
   client** public config for `JARVIS_FIREBASE_CLIENT_CONFIG` on the Jarvis PC
   (never the admin service account on Jarvis).
2. **Mobile relay** — Deploy `services/mobile-relay/` on a public Linux host with
   Compose, register this Jarvis installation via `POST /v1/register`, then set
   `JARVIS_RELAY_*`, `JARVIS_PUSH_*` on the Jarvis desktop. Restart Jarvis so the
   outbound relay agent connects.
3. **TURN** — Deploy and configure coturn (REST shared-secret) on a reachable host;
   set `JARVIS_TURN_URL` and `JARVIS_TURN_SECRET` on Jarvis.
4. **APK** — In the desktop companion panel, **Prepare connection**, then build a
   personalized release APK so endpoints and pins match (includes Firebase client
   fields when configured).
5. **Acceptance** — On a physical phone: incoming and background critical calls,
   audio routes, interruptions, and reconnection (not verified in CI).

**No public relay, Firebase, or TURN infrastructure is deployed or claimed by the
repository;** live acceptance remains blocked until Taco provisions hosts and secrets.

## Verification (2026-09-10)

- Android debug APK: built successfully.
- Android lint: passes; warnings include older pinned libraries and intentional
  Keystore/pinned-TLS/locally bundled WebView usage.
- 66 focused pairing/connectivity/mobile/auth/voice tests pass, including stale/replayed
  approvals, interrupted speech, real local TLS lifecycle, safe router mapping and
  six-digit code expiry/regeneration/rate limiting, scoped schedule edit/resume and
  ordered call reconnect offers.
- Personalized signed release build and APK signature verification passed at the
  previous checkpoint. That test APK used a loopback endpoint, not a live phone pairing.
- GitHub Android build, frontend build and backend checks passed on the connectivity
  checkpoint `1c72750`; the current development-branch integration was rebuilt locally.
- Broader pytest attempt: 109 passed before stopping at 5 failures. All 5 failures
  reproduced on untouched base `146adab`: shell benchmark missing `sh`, best-of-N
  fixture output missing, two Cursor installation assumptions, and a Linux-only
  Office expectation on Windows. The complete backend suite is not green.

## Remaining release acceptance

Operator env templates, `GET /api/mobile/manage/infrastructure`, and the checklist
above make the deploy path concrete; **no public infrastructure is deployed by this
PR.** Remaining items:

- End-to-end installer/gateway startup integration; personalized signing/build and
  owner-authenticated downloads are implemented, but not verified on a paired phone.
- Physical-phone incoming/background calls, audio routes, interruptions, reconnection,
  process recreation, foreground-service/permission behavior and device battery tests.
- Device acceptance for encrypted outbox recovery, coding approvals and schedule
  editing; generation artifacts await BlackGrid. Studio reports it as disconnected.
- Live-model and multi-node execution verification. The phone is a controller;
  this branch does not implement new swarm consensus or phone-side inference.
