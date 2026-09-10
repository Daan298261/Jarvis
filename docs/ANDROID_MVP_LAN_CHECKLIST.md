# Android companion — MVP LAN checklist (Taco)

Short, LAN-first path to pair the native companion to a Windows Jarvis PC on the same Wi‑Fi. **No Firebase, TURN, or public relay** required for this MVP.

Full build/API reference: [`docs/android-companion.md`](android-companion.md). Architect spec (do not treat as runbook): [`ANDROID_CLIENT.md`](../ANDROID_CLIENT.md).

**Example host in this doc:** `192.168.1.212` — replace with your PC’s IPv4 (`ipconfig`).

---

## 0. APK to install

| Source | Path / name |
| --- | --- |
| **Known debug snapshot** | `Jarvis-companion-debug-5c75f3e.apk` — built from commit [`5c75f3e`](https://github.com/Daan298261/Jarvis/commit/5c75f3e) (RFC-0059 companion merge). Keep the file **outside git** (Downloads, USB, or a shared drive). |
| **Gradle debug (repo tip)** | After a local debug build: `android\app\build\outputs\apk\debug\app-debug.apk` |
| **CI artifact** | GitHub Actions workflow **Android companion** → artifact `jarvis-android-debug` (`app-debug.apk`) |
| **Personalized release** | Desktop **Android companion** build → `data\mobile\builds\jarvis-<version>.apk` (see [`docs/android-companion.md`](android-companion.md)) |

**Rebuild from tip** when companion fixes landed after `5c75f3e`:

```powershell
cd <Jarvis-repo>
git fetch origin development
git checkout development
npm --prefix frontend ci
Push-Location frontend; npm exec -- vite build --config vite.orb.config.ts; Pop-Location
Push-Location android; .\gradlew.bat :app:assembleDebug; Pop-Location
# Install: android\app\build\outputs\apk\debug\app-debug.apk
```

Optional: rename to `Jarvis-companion-debug-<git rev-parse --short HEAD>.apk` for traceability.

---

## 1. PC — start Jarvis backend

Same machine that will run the mobile gateway. Backend stays on **localhost**; the phone never hits `:4780` directly.

```powershell
cd <Jarvis-repo>
# Normal desktop start (loads model when configured):
.\start-jarvis.ps1

# Or API-only while debugging pairing (no GGUF load):
.\start-jarvis.ps1 -SkipModelLoad
```

Confirm: `Invoke-RestMethod http://127.0.0.1:4780/api/health`

You do **not** need LAN bind on `:4780` for this path; pairing management uses localhost. (Optional LAN on `:4780` is for the browser PWA — see [`docs/INSTALL.md`](INSTALL.md) §11.)

---

## 2. PC — start mobile TLS gateway (LAN)

Use the **LAN IPv4** the phone will dial. `--host` is a **certificate SAN** (not the bind address); the gateway listens on `0.0.0.0:4781`.

```powershell
cd <Jarvis-repo>
$env:PYTHONPATH = 'backend'
python -m app.mobile.gateway --host 192.168.1.212 --port 4781
```

**Server pin (fingerprint):** printed at startup:

```text
Server fingerprint: <64 lowercase hex chars>
```

Same value is stored with the TLS key under `data\mobile\tls\` (gitignored). If you renew the cert but keep the key, the pin stays stable. The phone must trust this pin when connecting to `https://192.168.1.212:4781`.

**Windows firewall:** allow inbound **TCP 4781** on the private network profile for this test.

---

## 3. PC — six-digit pairing code

**Portal (owner UI):**

1. Open [http://127.0.0.1:4780](http://127.0.0.1:4780).
2. **Settings** → Android companion section, or open [http://127.0.0.1:4780/companion-pairing](http://127.0.0.1:4780/companion-pairing).
3. **Generate** (or **Regenerate**) pairing code — **6 digits**, ~10 minutes TTL.

**API (copy-paste):** requires the owner private key from Settings (never commit it).

```powershell
$key = "<paste-owner-private-key-from-Settings>"
$headers = @{ "X-Jarvis-Key" = $key }
Invoke-RestMethod -Method POST `
  -Uri "http://127.0.0.1:4780/api/mobile/manage/pairing-codes" `
  -Headers $headers -Body "{}" -ContentType "application/json"
# Response includes .code (6 digits) and .expires_at
```

Related owner routes: `POST /api/mobile/manage/pairing-codes/regenerate`, `GET /api/mobile/manage/pairing-codes/status`, `POST /api/mobile/manage/devices/{id}/confirm` (fingerprint).

---

## 4. Phone — install and pair

1. **Install** the debug APK (`Jarvis-companion-debug-5c75f3e.apk` or a fresh `app-debug.apk`). Enable “Install unknown apps” for your file manager if needed.
2. **Same Wi‑Fi** as the PC (no VPN isolating the phone).
3. In the app **More** (connection settings):
   - Endpoint: `https://192.168.1.212:4781`
   - **Server pin:** exact 64-hex fingerprint from the gateway console (step 2).
4. **Pair:** enter the **6-digit code** from the desktop when prompted.
5. On the **desktop pairing screen**, confirm the device **fingerprint** matches the pending phone, then **Confirm** / activate the device.
6. On the phone, finish **Connect** when the session is active.

---

## 5. Smoke tests (foreground)

| Check | Pass criteria |
| --- | --- |
| **Chat** | Send a short message; reply or task activity from the PC agent. |
| **Voice ping** | From Chat/voice UI while app is **foreground**: mic permission granted; partial transcript or TTS playback. Duplex path: WSS `/api/companion/voice/realtime` via the gateway (see RFC-0064). Clip STT/TTS HTTPS fallback if realtime is unavailable. |
| **Tasks / heartbeat** | Tasks screen loads; PC shows companion heartbeat if configured in desktop panel. |

Keep the gateway terminal open; if it stops, the phone loses TLS ingress immediately.

---

## 6. Gaps — emulator vs physical phone

| Area | Emulator (typical) | Physical phone (required for) |
| --- | --- | --- |
| TLS + 6-digit pairing + foreground chat | Often sufficient | Definitive sign-off |
| Duplex realtime voice (latency, barge-in) | Partial; mic/audio routing simplified | Real mic, speaker, Bluetooth |
| **Background** incoming call / process death | Unreliable or unsupported | **Telecom**, FCM wake, battery optimizations |
| **FCM** push / relay wake | Not meaningful without Firebase + relay deploy | Production-style incoming call |
| **Audio routes** (speaker, BT, wired) | Limited | User acceptance |
| **Battery** / Doze / OEM kill | N/A | Long-run stability |
| **WebRTC** over LAN without TURN | May work on same subnet | NAT edge cases; TURN optional for WAN |

This MVP explicitly does **not** provision Firebase, `JARVIS_TURN_*`, or `services/mobile-relay/` — see [`docs/android-companion.md`](android-companion.md) for remote/voice production checklist.

---

## 7. Security reminders

- No owner private keys, pairing codes, relay credentials, or `bootstrap.json` in git.
- Only `/api/companion/*` is exposed on `:4781`; owner APIs stay on localhost `:4780`.
- Revoke a lost device: `POST /api/mobile/manage/devices/{id}/revoke` (owner key) or desktop companion panel.

---

## Troubleshooting (quick)

| Symptom | Likely fix |
| --- | --- |
| Gateway: `Jarvis is offline` | Start backend on `127.0.0.1:4780` first. |
| Pin mismatch | Use the fingerprint from the **same** gateway process; don’t mix PCs or deleted `data\mobile\tls`. |
| Code expired | Regenerate on desktop; codes last ~10 minutes. |
| 429 on enroll | Wait one minute; rate limits on pairing attempts. |
| Phone can’t reach host | Ping `192.168.1.212`, check firewall :4781, confirm phone Wi‑Fi subnet. |
