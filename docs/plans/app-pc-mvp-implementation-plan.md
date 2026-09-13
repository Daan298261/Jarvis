# Implementation Plan: Android + PC LAN MVP

**Status:** active (implementers)  
**Linked spec:** [`docs/spec.md`](../spec.md) streams **A–G**  
**Runbook:** [`docs/ANDROID_MVP_LAN_CHECKLIST.md`](../ANDROID_MVP_LAN_CHECKLIST.md)  
**Base branch:** `development`  
**Date:** 2026-09-13  

Notion was unavailable in cloud (MCP auth); this page is the canonical implementation plan until copied to your task board.

---

## Overview

Ship a **LAN-first** MVP: phone installs a signed companion APK, pairs to the PC over **TLS :4781**, passes **6-digit code + server pin**, desktop confirms fingerprint, then **foreground chat + voice** against the **host** Jarvis model (no on-phone LLM).

Code for streams A–G is largely on `main` / `development` (through **v1.3.3** stable cut + **#220/#214/#231** promoted via **#232**). The remaining gap is **integration sign-off**, **operator runbook freshness**, and a short list of **product hardening** items—not greenfield features.

---

## Biggest blockers (ranked)

| Rank | Blocker | Type | Why it stops MVP | Mitigation |
| --- | --- | --- | --- | --- |
| **1** | **No physical LAN sign-off** | Human / ops | Emulator cannot prove TLS pin, mic, barge-in, OEM battery | Taco runs [`ANDROID_MVP_LAN_CHECKLIST.md`](../ANDROID_MVP_LAN_CHECKLIST.md) with **v1.3.3+** APK; record pass/fail per row §5 |
| **2** | **PC inference not running** | Ops | Chat/voice need host model or scripted stub; `-SkipModelLoad` only proves API | `start-jarvis.ps1` with GGUF profile **fast**; confirm `/api/inference` loaded before phone smoke |
| **3** | **Gateway + firewall bring-up** | Ops / UX | Phone never hits `:4780`; gateway is separate process; Win firewall blocks **4781** | Settings → **Prepare connection** (starts gateway via `CONNECTIVITY`); document firewall rule in checklist §2 |
| **4** | **Runbook / release drift** | Docs | Checklist still cited **1.2.0** APK; owners install wrong build | Point §0 at GitHub **v1.3.3+** generic APK; rebuild generic after each stable cut |
| **5** | **Stream F QR payload** | Product | Pair QR must include endpoint + pin + code (RFC-0074 + RFC-0065) | Verify pairing payload in `CompanionPairingPanel` + Android QR parser; add test if gap found |
| **6** | **Stream B latency polish** | Product | Social TTS / first-chunk timing; not blocking pair | RFC-0075 tests + optional TTS warm-start; default **Show work** already off |
| **7** | **Background voice / FCM** | Scope | Incoming call when app killed | **Out of LAN MVP** per checklist §6; separate RFC track |

**Not MVP blockers:** Stream **H** HexStrike (Blue + permit); on-phone GGUF; public relay/TURN.

---

## Requirements summary (from spec)

| ID | Requirement | Spec stream | Acceptance signal |
| --- | --- | --- | --- |
| R1 | Auto owner key + 6-digit code + QR + status GET | A | `tests/test_companion_pairing.py`; desktop pair without pre-set key |
| R2 | Phone offline orb + Home pair CTAs | E | OFFLINE Home shows red orb + Scan/Enter code |
| R3 | Prepare connection → endpoints + pin | F | `MobileCompanionSetup` **Prepare connection** → gateway ready |
| R4 | Signed installable APK | D | GitHub Release generic APK; JDK autodetect (#214) |
| R5 | Host voice/chat over TLS | G | §5 smoke: chat + voice foreground; RFC-0064 path |
| R6 | Social weather without tool loop | B | #220 merged; `tests/test_weather_briefing.py` |
| R7 | Play → load local model | C | HUD Play + `/api/model` poll (partial; desktop GPU sign-off) |

---

## Technical approach

- **Architecture unchanged:** Portal **localhost:4780** (owner APIs); **gateway 0.0.0.0:4781** (companion allowlist only).
- **Verification split:** Cloud agents = unit tests + APK build; **MVP done** only when Taco checklist §4–§5 passes on a physical phone.
- **Release train:** `development` → PR → `main` → tag `vX.Y.Z` + upload `JarvisCompanion-X.Y.Z-generic.apk`.

---

## Phase 0 — Promote & release (done / maintain)

- [x] Merge spec wave to `development` (#223–#231)
- [x] Stable cut to `main` (#232) including weather + JDK autodetect
- [x] GitHub Release **v1.3.3** + generic APK (prior cut)
- [ ] Tag **v1.3.4** after next version bump on `main` (optional housekeeping)
- [ ] Refresh [`ANDROID_MVP_LAN_CHECKLIST.md`](../ANDROID_MVP_LAN_CHECKLIST.md) §0 for current release artifact

---

## Phase 1 — Operator green path (P0, mostly Taco)

**Goal:** One documented path from cold PC to paired phone.

| Task | Owner | Details |
| --- | --- | --- |
| P1.1 | Taco | Install APK from [v1.3.3 release](https://github.com/Daan298261/Jarvis/releases/tag/v1.3.3) or rebuild from `main` |
| P1.2 | Taco | `start-jarvis.ps1` (with model for chat smoke) |
| P1.3 | Taco | Portal → Android companion → **Prepare connection**; note **server pin** + LAN URL |
| P1.4 | Taco | `/companion-pairing` → generate code; confirm fingerprint on enroll |
| P1.5 | Taco | Phone: endpoint, pin, code; verify **connected** + §5 table |
| P1.6 | Dev | File GitHub issue with checklist results (pass/fail per row) |

**Dependencies:** Same Wi‑Fi; Windows firewall **TCP 4781** private profile.

---

## Phase 2 — Product hardening (P1, dev PRs)

**Goal:** Close known spec checkboxes without scope creep.

| Task | RFC / stream | Suggested PR scope | Tests |
| --- | --- | --- | --- |
| P2.1 | F | Assert QR/json payload includes endpoint + pin + code end-to-end | `test_companion_pairing.py` |
| P2.2 | F | Surface gateway failure reason in Prepare connection UI (firewall hint) | manual + component test if feasible |
| P2.3 | B | RFC-0075: first-chunk social TTS + `tests/test_rfc0075_speak_path.py` green | pytest |
| P2.4 | C | Play button error surfacing when llama/LM Studio missing (HUD copy) | `test_runtime_activate.py` |
| P2.5 | D | Post–stable-cut: upload fresh generic APK to GitHub Release notes | release job |
| P2.6 | A | Spoken onboarding already wired; verify TTS gate on pair page with model loaded | `test_companion_pairing.py` onboarding |

One RFC or one checklist row **per PR** ([`docs/PROCESS.md`](../PROCESS.md)).

---

## Phase 3 — Post-MVP (explicitly later)

| Item | Note |
| --- | --- |
| Background incoming call / FCM | Checklist §6; needs Firebase + relay |
| WAN / TURN | Out of LAN MVP |
| Stream H HexStrike expansion | Daybreak Blue only |
| On-phone LLM | Not planned (RFC-0064) |

---

## Dependencies

| Dependency | Blocks |
| --- | --- |
| Windows PC + NVIDIA (for real replies) | Chat/voice quality smoke |
| TLS gateway running | All phone traffic |
| Owner private key (auto-mint OK) | Pairing codes |
| Signed APK on phone | Install step |

---

## Risks & mitigation

| Risk | Mitigation |
| --- | --- |
| Pair works on emulator but not phone | Physical sign-off required (blocker #1) |
| Wrong APK version | Release + checklist alignment (blocker #4) |
| Gateway stopped → phone dead | Checklist: keep gateway terminal open |
| Scope creep in one PR | This plan splits Phase 2 into single-purpose PRs |

---

## Success criteria (MVP = done)

1. [`ANDROID_MVP_LAN_CHECKLIST.md`](../ANDROID_MVP_LAN_CHECKLIST.md) **§4–§5** passed on a **physical phone** with a **current** generic APK and documented PC LAN IP.
2. `python3 -m pytest` green on `development`.
3. `main` contains the same companion/pairing code as the signed APK used in step 1.
4. No open **P0** issues filed from Phase 1 sign-off (or each has an owner + RFC).

---

## Suggested task board items (if using Notion/Jira)

Copy each **P1.x** and **P2.x** row as a task with:

- **Status:** To Do / In Progress / Blocked / Done  
- **Priority:** P0 for Phase 1, P1 for Phase 2  
- **Link:** this plan + [`docs/spec.md`](../spec.md) stream letter  

---

## Progress log

| Date | Note |
| --- | --- |
| 2026-09-13 | Plan created; `main` promoted via #232; blockers ranked; Phase 0–2 defined |
