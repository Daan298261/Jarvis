# Jarvis product spec — pairing, mobile, latency, Play-to-load, delivery, cyber suite

**Status:** working spec (implementers)  
**Base branch:** `development`  
**Date:** 2026-09-13  

This document consolidates owner-requested workstreams and related RFCs. **One RFC or one queue item per PR** ([`docs/PROCESS.md`](PROCESS.md)). Do not edit Architect-owned spec files (`JARVIS_MASTER_PLAN.md`, `SECURITY_AGENTS.md`, etc.) from these tickets; note queue implications in PR descriptions only.

---

## 1. Overview

| Stream | Goal | Primary RFC / area | Owner |
| --- | --- | --- | --- |
| **A. Phone pairing** | Streamline companion pairing; QR + code; auto owner key | RFC-0074 | Product |
| **B. PC response speed** | Faster replies, voice/social latency, collapsed thought UI | RFC-0075, RFC-0036 | Product |
| **C. Play button** | Play → discover → start runtime → load local model | RFC-0077, RFC-0073 | Product |
| **D. APK delivery UX** | Visible build progress; Download to Desktop; optional send | RFC-0076 | Product |
| **E. Mobile companion UX** | Presence orb offline state; Home pairing CTAs | RFC-0074, RFC-0059 | Product |
| **F. Connection bring-up** | TLS gateway + endpoints before pair/build | RFC-0065 | Product |
| **G. Mobile voice** | Realtime + clip voice over pinned TLS to **host** | RFC-0064 | Product |
| **H. Cyber suite (HexStrike)** | Full operator cyber surface | RFC-0078, RFC-0079 | **Daybreak Blue** |

Streams **A–G** are ordinary product work on `development`. Stream **H** and expanded cyber tooling are **Daybreak Blue** under **police permit** (authorization outside this doc; Blue task lists omit duplicate security review text).

---

## 2. Stream A — Streamline pairing (phone + desktop)

**RFC:** [`docs/rfcs/0074-companion-pairing-streamline-and-qr.md`](rfcs/0074-companion-pairing-streamline-and-qr.md)

### Problem

Pairing fails or feels heavy when the owner key is unset, the phone lives on **More**, enroll/status endpoints disagree with the UI cache, and there is no spoken walkthrough.

### Decision

1. **Auto owner key** on “Pair phone” intent (`backend/app/auth.py`; persist like Settings; never log secrets).
2. **Single owner path:** Pair → regenerable **6-digit code (RFC-0063)** + **QR (same payload)** → phone scan or type → owner **fingerprint confirm** on desktop.
3. **Fix green path** (name failing API in implement PR if still broken):

| Surface | Path | Likely failure |
| --- | --- | --- |
| Owner pair mint | `POST /api/mobile/manage/pairing-codes` (+ regenerate) | `403` when owner key unset (`require_owner_private_key`) |
| Owner pair status | `GET /api/mobile/manage/pairing-codes/status` | Frontend `getActiveCompanionPairingCode` cache-only today |
| Phone enroll | `POST /api/companion/enroll` | Verify after auto-mint + RFC-0065 endpoint |

4. **Phone UX:** OFFLINE Home → pair guidance; QR scan prefills endpoint, pin, code; one **Pair** CTA when complete.
5. **Spoken onboarding (RFC-0074 §4):** Butler steps for (a) pair phone vs (b) explore features (RFC-0049); no PLAN dump; align RFC-0067 TTS gates.

### Tasks

- [ ] Backend: auto-mint owner private key when pairing starts and key is missing
- [ ] Frontend: server-backed pairing code + TTL; large QR on full pair panel; call status GET
- [ ] Android: streamlined pair flow; QR parser → prefilled fields; minimal steps after scan
- [ ] Spoken offer: pair phone vs explore (persona / owner chat hook)
- [ ] Tests: `tests/test_companion_pairing.py`, `tests/test_mobile_companion.py`
- [ ] Desktop + phone sign-off: unset key → 200 code + QR → enroll → fingerprint approve

### Likely files

`backend/app/auth.py`, `backend/app/api/companion.py`, `backend/app/mobile/identity.py`, `frontend/src/api.ts`, `frontend/src/components/CompanionPairingPanel.tsx`, `frontend/src/pages/CompanionPairing.tsx`, `android/.../MainActivity.kt`, `CompanionPairingQr.kt`, `CompanionCodeValidator.kt`

### Out of scope

RFC-0059 Android Keystore redesign; cloud-account pairing; baking long invitation strings as primary UX.

---

## 3. Stream B — Increase Jarvis response speed on PC

**RFC:** [`docs/rfcs/0075-natural-speak-path-and-reply-latency.md`](rfcs/0075-natural-speak-path-and-reply-latency.md), [`docs/rfcs/0036-interaction-latency-and-streaming-talkback.md`](rfcs/0036-interaction-latency-and-streaming-talkback.md)

### Problem

Social/voice turns wait for full tool loops (~10s+); TTS reads markdown and errors; thought/process visible by default.

### Decision

| Class | Heuristic (testable) | Speak behavior |
| --- | --- | --- |
| **Social** | Short weather/time/greeting; no fences/traces | Natural prose; first stable sentence TTS when safe; ack ≲700ms where RFC-0036 applies |
| **Technical** | Code, diffs, tool dumps | Still filtered — no fences/URLs/traces aloud |

- Extend `filter_text_for_speech` (RFC-0070 / RFC-0068).
- Owner chat + HUD: **final reply only**; work behind collapsed chevron (`jarvis.chat.showWork` default off).

### Tasks

- [ ] Social routing: weather-style asks stay conversational (see also RFC-0084 / Open-Meteo briefing on `development`)
- [ ] First-chunk TTS enqueue for social class when semantically safe
- [ ] Speak filter: no `**`, `#`, list markers, URLs, stack traces in TTS
- [ ] HUD + Classic: thought collapsed by default (`OwnerChatTranscript`, `HudChat`)
- [ ] Tests: `tests/test_rfc0075_speak_path.py`, `tests/test_planning.py`, persona RFC-0061 tests
- [ ] Optional: TTS warm-start on boot (`backend/app/tts/warm_start.py`) — keep loaded after Play for N minutes

### Likely files

`backend/app/persona/chat_delivery.py`, `backend/app/persona/owner_chat.py`, `backend/app/tts/speak_filter.py`, `backend/app/tts/reply_class.py`, `backend/app/agent/planning.py`, `backend/app/agent/loop.py`, `frontend/src/chat/OwnerChatTranscript.tsx`, `frontend/src/hud/HudChat.tsx`

### Acceptance (from RFC-0075)

- [ ] Weather example speaks “eighteen to eleven degrees”, not asterisk markup
- [ ] Short social speech starts before full turn completion when safe
- [ ] Thought UI default collapsed

---

## 4. Stream C — Play button: auto-start and load local models

**RFC:** [`docs/rfcs/0077-local-lmstudio-discovery-and-hotswap-context.md`](rfcs/0077-local-lmstudio-discovery-and-hotswap-context.md), [`docs/rfcs/0073-hud-model-hotswap-selector.md`](rfcs/0073-hud-model-hotswap-selector.md)

### Problem

Play on a discovered local GGUF should not require a separate LM Studio / llama.cpp ritual; Admin/Legacy must not overlap the hotswap panel (RFC-0077).

### Decision

On **Play** (catalog row or slot):

1. `selectLmStudioProfile` / bind catalog id → runtime profile (RFC-0077).
2. **Ensure** backend runtime is up (llama.cpp attach or LM Studio per profile).
3. `activate_runtime_profile` → wait until `/api/model` shows **loaded** (or explicit error).
4. HUD: **Loading… / Loaded / last_error** on selector; conversation context **not** reset (hotswap).
5. **HexStrike suite** row: `startHexStrike()` only — no `MANAGER.load`.

Slot persistence: `jarvis_hud_model_slots` in localStorage (RFC-0073); do not add parallel backend registry.

### Tasks

- [ ] Backend: idempotent ensure-runtime + load in `hotswap.py` / `lmstudio.py` / `runtime_profiles.py`
- [ ] Frontend: Play blocks until load confirm; refresh catalog + model status
- [ ] Chrome: reflow HUD when menu open (no Admin/Legacy overlap)
- [ ] Tests: `tests/test_runtime_activate.py`, `tests/test_owner_chat_hotswap.py`, `tests/test_lmstudio_catalog.py`, `tests/test_default_candidates.py`

### Likely files

`backend/app/inference/hotswap.py`, `backend/app/inference/manager.py`, `backend/app/api/lmstudio.py`, `backend/app/api/runtime_profiles.py`, `frontend/src/hud/HudModelSelector.tsx`, `frontend/src/hud/applyRuntimeProfile.ts`, `frontend/src/lmstudio/LmStudioCatalogPicker.tsx`

---

## 5. Stream D — Companion APK delivery UX

**RFC:** [`docs/rfcs/0076-companion-apk-delivery-ux.md`](rfcs/0076-companion-apk-delivery-ux.md)

### Problem

Owners cannot see build progress; weak download CTA; no optional WhatsApp/email send when integrations exist.

### Decision

- Visible states: **Queued / Building / Ready / Failed** (+ stale heartbeat, retry).
- Primary **Download to Desktop** from `GET /api/mobile/manage/builds/{id}/apk`; filename `JarvisCompanion-<rev>.apk`.
- Optional send when Gmail/WhatsApp configured; disabled + Setup link when not; soft-fail if send API missing.
- No secrets in APK beyond RFC-0059 public trust + pairing flow.

### Tasks

- [x] `CompanionApkBuildPanel`, `MobileCompanionSetup`, `api.ts` send helpers (landed on `development`)
- [x] Backend send paths: `backend/app/mobile/apk_delivery.py`, companion routes (when present)
- [ ] Desktop sign-off: Windows save-as; live send; personalized build still via owner keystore script
- [ ] Release hygiene: signed generic APK on GitHub Release (not unsigned release artifact)

### Likely files

`frontend/src/components/CompanionApkBuildPanel.tsx`, `frontend/src/pages/MobileCompanionSetup.tsx`, `frontend/src/api.ts`, `backend/app/api/companion.py`, `backend/app/mobile/apk_delivery.py`, `tests/test_companion_apk_send.py`

---

## 6. Stream E — Mobile companion UX (presence + offline)

**Related:** RFC-0074 (pair CTAs), RFC-0059 (companion app), RFC-0064 (voice host-side)

### Problem

Home screen looked empty when **OFFLINE** (orb missing or invisible); pairing buried under **More**.

### Decision

- Pass **connected=false** into bundled orb WebView (`setJarvisConnected`).
- Map disconnected idle → **offline** ApexOrb: diffused **red**, slower waves, `OFFLINE` label.
- Scale orb in WebView; push JS state on `onPageFinished`.
- Pairing CTAs from Stream A on Home when offline.

### Tasks

- [ ] Land offline orb + WebView fixes (PR track: mobile orb offline)
- [ ] Rebuild APK assets (`vite.orb.config.ts` before Gradle); generic release **signed** for sideload
- [ ] With Stream A: single-tap path from Home to QR scan

### Likely files

`frontend/mobile-orb/index.tsx`, `frontend/mobile-orb/orb.css`, `frontend/src/vendor/apex-ui/ApexOrb.jsx`, `android/.../MainActivity.kt` (`PresenceHud`)

---

## 7. Stream F — Connection bring-up (before pair / build)

**RFC:** [`docs/rfcs/0065-*.md`](rfcs/) (PC endpoint bring-up — see master plan / RFC-0065 reference in RFC-0074)

### Problem

Companion pair and personalized APK need a prepared **HTTPS gateway** and endpoint list.

### Decision

Desktop **Prepare connection** (`MobileCompanionSetup`) enables TLS ingress, surfaces endpoints + server pin; QR/code payload includes same origin (RFC-0074 + RFC-0065).

### Tasks

- [ ] Document green path: Prepare connection → pair QR/code includes endpoint + pin
- [ ] Verify `CONNECTIVITY.snapshot()` endpoints flow into pairing payload and Android bootstrap
- [ ] Tests: mobile connectivity / gateway tests on `development`

### Likely files

`backend/app/mobile/connectivity.py`, `backend/app/mobile/gateway.py`, `frontend/src/pages/MobileCompanionSetup.tsx`, `scripts/build_android.py`

---

## 8. Stream G — Mobile voice (host inference, not on-phone LLM)

**RFC:** [`docs/rfcs/0064-android-realtime-voice.md`](rfcs/0064-android-realtime-voice.md)

### Problem

Owner asked about a tiny on-phone model for voice chat.

### Decision (product)

- **No on-phone chat LLM** in current architecture. Phone: capture, playback, VAD; **STT/TTS/reasoning on paired Jarvis host** via pinned TLS.
- Realtime: WSS `/api/companion/voice/realtime`; fallback clip STT/TTS HTTPS.
- Optional future on-device download **≤50 MiB** (wake-word/VAD only) — opt-in per RFC-0064; does not replace host replies.

### Tasks

- [ ] Document in Help topic `phone-pairing` / voice (already partial in `backend/app/help/topics.py`)
- [ ] Android Chat/Home: show model + voice pickers; `inference.loaded` status when connected (RFC-0084 track on `development`)
- [ ] Do not add phone-side GGUF loader without new RFC

### Out of scope

On-device 9B/27B; voice without gateway connection.

---

## 9. Stream H — Cybersecurity / HexStrike — to be handled by Daybreak Blue

**RFC:** [`docs/rfcs/0078-hexstrike-cyber-suite.md`](rfcs/0078-hexstrike-cyber-suite.md), [`docs/rfcs/0079-computer-use-permission-selector.md`](rfcs/0079-computer-use-permission-selector.md)  
**Owner:** **Daybreak Blue**  
**Authorization:** **Police permit**

Jarvis ships the **suite shell** (HUD profile, loopback supervisor, allowlisted `/api/hexstrike` gateway, `hex_aegis` presence, tests). Upstream [`0x4m4/hexstrike-ai`](https://github.com/0x4m4/hexstrike-ai) is **not** vendored in-repo.

### Blue-owned tasks

- to be handled by **Daybreak Blue** — Clone/pull HexStrike into `runtime/hexstrike-ai` or `JARVIS_HEXSTRIKE_HOME`
- to be handled by **Daybreak Blue** — Bootstrap script (venv, deps, `python hexstrike_server.py --port 8888`, smoke health)
- to be handled by **Daybreak Blue** — HUD install-missing UX + help topic for operators
- to be handled by **Daybreak Blue** — Expand Jarvis ↔ HexStrike to **full permitted operator feature set** (MCP, commands, dashboards — as authorized under permit)
- to be handled by **Daybreak Blue** — Wire **computer-use / cyber** permissions (`ComputerUsePermissions`, `backend/app/policy/computer_permissions.py`) for owner-approved scopes
- to be handled by **Daybreak Blue** — PolitieGPT / LE gate where permit requires case-bound actions
- to be handled by **Daybreak Blue** — Desktop sign-off: live install, HUD console, telemetry/process views

### Product repo (maintain only — no expansion in generic PRs)

`backend/app/security/hexstrike.py`, `backend/app/api/hexstrike.py`, `frontend/src/hud/HudHexStrikeSuite.tsx`, `HudModelSelector.tsx`, `tests/test_hexstrike_suite.py`

---

## 10. Adjacent RFCs (reference only — separate tickets)

| RFC | Topic | Note |
| --- | --- | --- |
| RFC-0070 | TTS engines / Kokoro | Engine choice; pairs with Stream B filter |
| RFC-0072 | ACP interoperability | Editor/agent protocol; not pairing |
| RFC-0078 (help) | In-app Help + Qwen3.8 default | [`0078-in-app-help-and-qwen38-9b-default.md`](rfcs/0078-in-app-help-and-qwen38-9b-default.md) — distinct from HexStrike 0078 |
| RFC-0081–0083 | Boot nova, spoken permissions, follow-ups | Landed 1.3.2 |
| RFC-0080 | JDK autodetect for APK builds | Open PR track |
| RFC-0084 | Weather conversational + Android model status | Open PR track |

Implement each only when named as the single ticket for a PR.

---

## 11. Dependencies

| Dependency | Blocks |
| --- | --- |
| Owner PC running Jarvis + inference | B, C, G |
| TLS gateway + endpoints (Stream F) | A, personalized APK |
| Owner key + pairing codes | A |
| Gmail/WhatsApp integrations | D send (optional) |
| `runtime/hexstrike-ai` install | H (Blue) |
| Police permit | H expansion (Blue) |
| GitHub Release signed APK | D sideload testing |

---

## 12. Risks

| Risk | Mitigation |
| --- | --- |
| Pairing still fails on LAN/TLS | Matrix: generic vs personalized APK; QR includes pin + endpoint |
| Play starts wrong backend | Bind Play to catalog id; show active model in HUD |
| Social TTS speaks too early | RFC-0036 — no false claims before tool result |
| Unsigned APK on Release | Sign release with debug/sidload key in CI; document in release notes |
| Scope creep (many streams one PR) | One RFC per PR; this spec is index only |
| Cyber work in product PRs | Stream H explicitly Blue-only |

---

## 13. Current implementation status (snapshot)

| Item | Status on `development` |
| --- | --- |
| RFC-0076 APK delivery UI + send backend | Largely landed |
| RFC-0078 HexStrike suite shell | Implemented (RFC marked implemented) |
| RFC-0073/0077 HUD hotswap + LM catalog | Partial — Play/load hardening open (Stream C) |
| RFC-0074 pairing auto-key + spoken | Spec accepted — implement open (Stream A) |
| RFC-0075 speak path | Partial — tests exist; chevron/latency remainder |
| Offline red orb (Stream E) | PR track |
| HexStrike clone in repo | Not vendored — Blue setup |
| On-phone LLM voice | Not planned (Stream G) |

---

## 14. Verification

| Stream | Command / sign-off |
| --- | --- |
| A | `python3 -m pytest` pairing + mobile; `npm --prefix frontend run build`; phone + desktop pair |
| B | `python3 -m pytest` speak-path, planning, owner chat; desktop voice social prompt |
| C | `python3 -m pytest` runtime activate, hotswap, LM catalog; HUD Play → loaded |
| D | `npm --prefix frontend run build`; `tests/test_companion_apk_send.py`; desktop download/send |
| E | Android build + orb visible offline on device |
| F | Gateway up; endpoints in QR payload |
| G | Connected phone Talk; host shows loaded model |
| H | Blue + permit; not generic CI |

---

## 15. Ticket split (recommended order)

1. **RFC-0074** — Pairing + QR + auto key + spoken onboarding (A)  
2. **Stream E** — Offline orb + Home pair CTAs (can merge with A if one UX PR)  
3. **RFC-0075** — Latency + speak remainder (B)  
4. **RFC-0077 / RFC-0073** — Play ensure start + load (C)  
5. **RFC-0076** — Remaining delivery sign-off + release APK hygiene (D)  
6. **RFC-0065** — Connection bring-up docs/tests if pair still blocked (F)  
7. **Daybreak Blue** — HexStrike pull + permitted cyber surface (H)  

---

## 16. References

- [`docs/PROCESS.md`](PROCESS.md)
- [`docs/rfcs/0074-companion-pairing-streamline-and-qr.md`](rfcs/0074-companion-pairing-streamline-and-qr.md)
- [`docs/rfcs/0075-natural-speak-path-and-reply-latency.md`](rfcs/0075-natural-speak-path-and-reply-latency.md)
- [`docs/rfcs/0076-companion-apk-delivery-ux.md`](rfcs/0076-companion-apk-delivery-ux.md)
- [`docs/rfcs/0073-hud-model-hotswap-selector.md`](rfcs/0073-hud-model-hotswap-selector.md)
- [`docs/rfcs/0077-local-lmstudio-discovery-and-hotswap-context.md`](rfcs/0077-local-lmstudio-discovery-and-hotswap-context.md)
- [`docs/rfcs/0078-hexstrike-cyber-suite.md`](rfcs/0078-hexstrike-cyber-suite.md)
- [`docs/rfcs/0079-computer-use-permission-selector.md`](rfcs/0079-computer-use-permission-selector.md)
- [`docs/rfcs/0064-android-realtime-voice.md`](rfcs/0064-android-realtime-voice.md)
- [`docs/android-companion.md`](android-companion.md)
- [`SECURITY_AGENTS.md`](../SECURITY_AGENTS.md) — Architect; Blue/Purple/Red roles
