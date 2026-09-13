# Jarvis product spec — pairing, latency, Play-to-load, cyber suite

**Status:** working spec (implementers)  
**Base branch:** `development`  
**Date:** 2026-09-13  

This document consolidates owner-requested workstreams. **One RFC or one queue item per PR** ([`docs/PROCESS.md`](PROCESS.md)). Do not edit Architect-owned spec files (`JARVIS_MASTER_PLAN.md`, `SECURITY_AGENTS.md`, etc.) from these tickets; note queue implications in PR descriptions only.

---

## 1. Overview

| Stream | Goal | Primary RFC / area |
| --- | --- | --- |
| **A. Phone pairing** | Streamline companion pairing on the phone; QR-first; green path when no owner key yet | RFC-0074 |
| **B. PC response speed** | Faster Jarvis replies, especially voice and social turns | RFC-0075, RFC-0036 |
| **C. Play button** | Press Play → discover local model → start runtime if needed → load | RFC-0077, RFC-0073 |
| **D. Cyber suite (HexStrike)** | Full cybersecurity operator surface | RFC-0078 — **to be handled by Daybreak Blue** |

Streams **A–C** are ordinary product work on `development`. Stream **D** and any expanded offensive-adjacent tooling are **Daybreak Blue** delivery under **police permit** (authorization handled outside this spec; no duplicate security review text in Blue task lists below).

---

## 2. Stream A — Streamline pairing (phone + desktop)

**RFC:** [`docs/rfcs/0074-companion-pairing-streamline-and-qr.md`](rfcs/0074-companion-pairing-streamline-and-qr.md)

### Problem

Pairing fails or feels heavy when the owner key is unset, the phone lives on **More**, and enroll/status endpoints are inconsistent with the UI cache.

### Decision

1. **Auto owner key** on “Pair phone” intent (reuse `backend/app/auth.py`; never log secrets).
2. **Single owner path:** Pair → 6-digit code + **same-session QR** → phone scan or type code → desktop fingerprint confirm.
3. **Fix green path:** `GET /api/mobile/manage/pairing-codes/status`; stop cache-only pairing in `frontend/src/api.ts`.
4. **Phone UX:** When **OFFLINE**, Home guides to pair (not only **More**); after QR scan, prefilled endpoint/pin/code and one primary **Pair** CTA.

### Tasks

- [ ] Backend: auto-mint owner private key when pairing starts and key is missing
- [ ] Frontend: server-backed pairing code + TTL; QR on full pair panel
- [ ] Android: streamlined pair screen; deep link / QR payload → minimal confirm step
- [ ] Tests: `tests/test_companion_pairing.py`, mobile companion coverage
- [ ] Desktop + phone sign-off: unset key → pair → approve fingerprint

### Likely files

`backend/app/auth.py`, `backend/app/api/companion.py`, `backend/app/mobile/identity.py`, `frontend/src/api.ts`, `frontend/src/components/CompanionPairingPanel.tsx`, `android/.../MainActivity.kt`, `CompanionPairingQr.kt`

### Out of scope

RFC-0059 Keystore redesign; RFC-0076 APK delivery (separate); on-phone LLM (RFC-0064 keeps STT/TTS on host).

---

## 3. Stream B — Increase Jarvis response speed on PC

**RFC:** [`docs/rfcs/0075-natural-speak-path-and-reply-latency.md`](rfcs/0075-natural-speak-path-and-reply-latency.md)

### Problem

Social and voice turns wait for full tool loops; TTS reads markup; thought chrome adds perceived latency.

### Decision

- Classify **social vs technical** before speak; social weather/greeting stays conversational.
- **First stable sentence** TTS for social class when safe (RFC-0036 budgets).
- Speak filter: no `**`, fences, URLs, stack traces aloud.
- Owner chat: thought/process **collapsed by default** (chevron).

### Tasks

- [ ] Harden social routing (no unnecessary 28-step loop for weather-style asks)
- [ ] First-chunk TTS enqueue for social class
- [ ] Extend speak-filter tests (`tests/test_rfc0075_speak_path.py`, persona tests)
- [ ] HUD + Classic: default collapsed “Show work”
- [ ] Optional: short post-Play model warm window to avoid reload latency

### Likely files

`backend/app/persona/chat_delivery.py`, `backend/app/tts/speak_filter.py`, `backend/app/agent/planning.py`, `frontend/src/chat/OwnerChatTranscript.tsx`, `frontend/src/hud/HudChat.tsx`

---

## 4. Stream C — Play button: auto-start and load local models

**RFC:** [`docs/rfcs/0077-local-lmstudio-discovery-and-hotswap-context.md`](rfcs/0077-local-lmstudio-discovery-and-hotswap-context.md), [`docs/rfcs/0073-hud-model-hotswap-selector.md`](rfcs/0073-hud-model-hotswap-selector.md)

### Problem

Play on a discovered local model should not require a separate “start LM Studio / load GGUF” ritual.

### Decision

When the operator presses **Play** on a catalog row or slot:

1. Resolve runtime profile for that GGUF (LM Studio discovery).
2. If local inference is down, **start or attach** to the configured backend (llama.cpp / LM Studio per profile).
3. **Load** the model and return only when `/api/model` reports loaded (or a clear error).
4. HUD shows **Loading… / Loaded / error** on the play control.

HexStrike **suite** Play follows existing suite activation (`startHexStrike`) — not `MANAGER.load`.

### Tasks

- [ ] Backend: idempotent “ensure runtime up + load profile” in hotswap / LM Studio activate path
- [ ] Frontend: Play waits for load confirmation; surface `model.loading` / errors on HUD
- [ ] Tests: `tests/test_runtime_activate.py`, `tests/test_owner_chat_hotswap.py`, LM catalog tests

### Likely files

`backend/app/inference/hotswap.py`, `backend/app/api/lmstudio.py`, `backend/app/api/runtime_profiles.py`, `frontend/src/hud/HudModelSelector.tsx`, `frontend/src/hud/applyRuntimeProfile.ts`

---

## 5. Stream D — Cybersecurity / HexStrike — to be handled by Daybreak Blue

**RFC:** [`docs/rfcs/0078-hexstrike-cyber-suite.md`](rfcs/0078-hexstrike-cyber-suite.md)  
**Owner:** **Daybreak Blue** (household defensive / authorized operator lane)  
**Authorization:** **Police permit** — scope and lawful use are defined in that process, not repeated in product task checklists below.

Jarvis already ships the **suite shell**: HUD ModelSelector row, `hex_aegis` presence, loopback supervisor, same-origin `/api/hexstrike` gateway, and unit tests. Upstream **HexStrike AI** is **not** vendored in this repo; install lives beside Jarvis (e.g. `runtime/hexstrike-ai`).

### Blue-owned tasks (no product guardrail copy here — permit governs)

- to be handled by **Daybreak Blue** — Clone/pull [`0x4m4/hexstrike-ai`](https://github.com/0x4m4/hexstrike-ai) into `runtime/hexstrike-ai` (or `JARVIS_HEXSTRIKE_HOME`) and document one-shot setup for operators
- to be handled by **Daybreak Blue** — Windows installer or bootstrap script: venv, dependencies, smoke `GET /health` on loopback
- to be handled by **Daybreak Blue** — HUD “install missing” path: copy setup command, open help topic, verify suite start from ModelSelector
- to be handled by **Daybreak Blue** — Expand Jarvis ↔ HexStrike integration to the **full operator feature set** required under police permit (MCP tools, command paths, dashboards, process control — as authorized)
- to be handled by **Daybreak Blue** — Register HexStrike capabilities with **computer-use / cyber permissions** UI (`ComputerUsePermissions`) for owner-approved scopes
- to be handled by **Daybreak Blue** — Physical-device sign-off: suite running, HUD console, telemetry and process views on reference PC
- to be handled by **Daybreak Blue** — PolitieGPT / LE gate wiring where permit requires named bot or case-bound actions

### Product repo (already landed — maintain only)

- Suite profile `hexstrike-suite`, `backend/app/security/hexstrike.py`, `backend/app/api/hexstrike.py`
- `frontend/src/hud/HudHexStrikeSuite.tsx`, `HudModelSelector.tsx`, `hexAegis` presence shape
- `tests/test_hexstrike_suite.py`

**Note for implementers:** Do **not** implement Stream **D** expansion in generic cloud/product PRs. Open Blue-track PRs or hand off to Daybreak Blue after permit is in place.

---

## 6. Dependencies

| Dependency | Blocks |
| --- | --- |
| Owner PC running Jarvis + inference | B, C; mobile voice (host STT/TTS) |
| TLS gateway / endpoint (RFC-0065) | A — phone pair over LAN |
| `runtime/hexstrike-ai` install | D — live suite (Blue) |
| Police permit | D — expanded cyber functionality (Blue) |

---

## 7. Verification

| Stream | Command / sign-off |
| --- | --- |
| A | `python3 -m pytest` pairing tests; `npm --prefix frontend run build`; phone + desktop pair soak |
| B | `python3 -m pytest` speak-path / planning tests; voice social prompt on desktop |
| C | `python3 -m pytest` runtime activate / hotswap; HUD Play → loaded model |
| D | Blue + desktop sign-off under permit; not required for A–C PR CI |

---

## 8. Ticket split (recommended)

1. **RFC-0074** — Pairing streamline (phone + auto key)  
2. **RFC-0075** — Latency + speak path remainder  
3. **RFC-0077** — Play ensures start + load  
4. **Daybreak Blue** — HexStrike pull, setup, full permitted cyber surface (§5)

---

## 9. References

- [`docs/rfcs/0074-companion-pairing-streamline-and-qr.md`](rfcs/0074-companion-pairing-streamline-and-qr.md)
- [`docs/rfcs/0075-natural-speak-path-and-reply-latency.md`](rfcs/0075-natural-speak-path-and-reply-latency.md)
- [`docs/rfcs/0077-local-lmstudio-discovery-and-hotswap-context.md`](rfcs/0077-local-lmstudio-discovery-and-hotswap-context.md)
- [`docs/rfcs/0078-hexstrike-cyber-suite.md`](rfcs/0078-hexstrike-cyber-suite.md)
- [`SECURITY_AGENTS.md`](../SECURITY_AGENTS.md) — Blue / Purple / Red roles (Architect; do not edit in product PRs)
