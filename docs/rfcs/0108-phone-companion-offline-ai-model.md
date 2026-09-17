# RFC-0108: Phone companion offline AI model

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent / index:** [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) (Taco priority #2).  
**Related (do not rewrite):** RFC-0039 Android native client (Leader remains authoritative **when reachable**). RFC-0059 companion delivery (implemented). RFC-0064 / RFC-0066 realtime voice. RFC-0074 pairing + QR. RFC-0076 APK delivery UX. RFC-0032 ultra-low-bit / edge routing (**optional ephemeral worker is not this ticket**). RFC-0035 tiny command front-end (host-side; this RFC is **on-device**). RFC-0092 neural TTS default (**do not rewrite**; phone TTS/STT stay as today unless 0092 already landed). `ANDROID_CLIENT.md` (phone is a controller, not P3 swarm). `docs/android-companion.md`.

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not put GGUF weights in git.

## Problem

The Android companion (`android/`) is a paired controller: chat, tasks, attachments, Apex orb, and voice all assume the Windows Leader (`/api/companion`, TLS gateway `:4781`). RFC-0039 / RFC-0059 / `ANDROID_CLIENT.md` say the Leader owns agents, models, memory, and policy. That is correct **online**.

When the PC is off, asleep, or the phone is off-LAN without WAN, the companion cannot answer. Encrypted `Outbox` only holds a pending **submission** until the Leader returns — it is not an offline brain. Taco’s add: the companion must run a **local on-device model** so the phone still talks, and **PC Jarvis remains the orchestrator whenever it is online**. RFC-0032 explicitly left “shipping a mobile model runtime in the Android control client” out of scope; this RFC names that product.

A decorative “offline — connect to PC” banner with no local inference is a **fail**. A second full Jarvis (own memory authority, own HexStrike, own swarm) on the phone is also a fail.

## Decision

Extend the **existing** companion with an **on-device inference runtime**. One Android product. One brain when the Leader is reachable.

### 1. Roles

| Mode | Who reasons | What the phone does |
| --- | --- | --- |
| **Online** (Leader reachable, paired session live) | **PC Jarvis orchestrator** (9B/27B / current profile) | Controller: chat/tasks/voice/studio as today. Optional: on-device model as a **low-latency front-end** (classify / short reply) that **hands off** to Leader for tools, memory, and policy — does not silently replace the host agent. |
| **Offline** (no Leader / no session) | **On-device model** | Local chat + bounded device actions that do not need the PC (show last synced snapshot, draft replies, capture attachments for later, queue work). Persist turns on-device. |

When the session returns, the phone **syncs**: upload queued user turns + local assistant drafts to Leader conversations (stable request ids; existing Outbox / pending-message patterns). Leader memory/policy remain canonical; offline drafts are labeled as device-local until the orchestrator accepts or rewrites them. Do not fork a second ContextRepo on the phone.

### 2. On-device runtime (real, not a stub)

Ship a working local LLM path inside the APK **or** as an owner-downloaded pack the app loads from app-private storage:

1. **Runtime:** in-process engine capable of GGUF (or equivalent documented mobile format) on CPU / NPU / GPU as the device allows. Prefer a llama.cpp-class Android backend already used in the ecosystem (or ExecuTorch / LiteRT-LM if the implement ticket measures a strictly better fit on target phones). One engine in v1. Record the choice in the implement PR; do not leave “TODO pick runtime.”
2. **Weights:** **not** in git. Owner downloads a **phone-sized** instruct GGUF (order: 1B–3B class first; larger only if the device reports enough RAM). Catalog is a pinned allowlist of filenames/URLs or a Leader-mediated pack (APK builder / companion settings), never an arbitrary web scrape. Progress is visible; failure is recoverable; missing weights show **install**, not a fake chat.
3. **Quality bar:** offline chat must return model tokens on a device with the pack installed. Mock completions, canned strings, or “model coming soon” as the shipped path are **fails**.
4. **Resources:** respect thermal/battery; do not keep a 27B-class host profile on the phone; do not evict companion UX to load a giant model. If the device cannot load the selected pack, refuse with an actionable reason (RAM/storage), do not crash-loop.

Phone STT/TTS stay the existing companion paths (clip / RFC-0064 WSS when online). This RFC does **not** change host RFC-0092 defaults. Offline TTS may use the existing on-device Android speech APIs for playback of local replies; it must not reintroduce silent SAPI on the **PC**.

### 3. What offline may and must not do

**May (v1):** local Q&A against the on-device model; read last-synced conversation/task snapshot cached on device; compose a message/attachment into Outbox; capture camera/gallery for later Leader analyze (RFC-0109); show honest connectivity (“Leader unreachable — answering on-device”).

**Must not (v1):** start HexStrike / RFC-0105 tools; mutate Leader filesystem; claim BlackGrid gen is running on the phone; become a swarm Node / RFC-0032 ephemeral worker (that remains a separate enrollment). Tool-using work **queues for the Leader**.

Pairing, Keystore identity, TLS pins, and revocation (RFC-0059 / 0074) stay required for **online** mode. Offline mode does not weaken pairing when the Leader returns.

### 4. Surfaces

- Companion **More / Models**: status (`missing` / `downloading` / `ready` / `running` / `error`), selected pack, storage used, **Download**, delete pack.
- Chat: offline banner + local stream; when Leader returns, banner clears and sync runs.
- Desktop pairing / Phone page: optional “companion model pack” hint; Leader does not need the GGUF resident to pair.

**Architect’s initial recommendation:** `partial` — on-device runtime inside the existing companion, Leader orchestrator online. Taco can override pack size / engine, not the online-orchestrator rule.

**Will not:** second Jarvis on the phone; vendor weights; P3 swarm phone role; rewrite RFC-0092; persona merge; HexStrike-on-device; invented LE gates.

## Acceptance criteria

- [ ] Specs-only in this PR (no `android/` / `frontend/src` / backend product edits; no GGUFs committed)
- [ ] Online: Leader remains orchestrator; companion stays the paired controller
- [ ] Offline: on-device model produces real tokens when the pack is installed; no canned-stub deliverable
- [ ] Queued turns sync to Leader with stable ids; no second memory authority
- [ ] Pack download/progress/delete; missing pack is installable, not a fake chat
- [ ] Not a swarm `PHONE` node; not HexStrike-on-phone
- [ ] RFC-0092 / host TTS defaults not rewritten here
- [ ] Light §59 Decision Log line only (via `INTEGRATION_SPECS.md` batch)
- [ ] Implement follow-up: Android unit tests + `python3 -m pytest` for sync API; live token generation is **device sign-off** (cloud VM cannot)

## Likely files

| Area | Paths |
| --- | --- |
| Android (implement PR only) | `android/app/src/main/java/com/jarvis/companion/` — new inference module (load/generate/unload); `CompanionModel.kt` online/offline routing; `Outbox.kt` multi-turn queue; `MainActivity.kt` banner + Models UI; Gradle native `.so` / engine wrap |
| Backend (implement PR only) | `backend/app/api/companion.py` + `backend/app/mobile/service.py` — conversation sync of device-local turns; optional pack catalog metadata (URLs/hashes only) |
| Frontend (implement PR only) | Phone / companion pairing hint for pack status — not a desktop model loader |
| Tests | `android/app/src/test/...` routing/outbox; `tests/test_rfc0108_*.py` sync contract (offline labeled, Leader canonical) |
| Docs | this RFC; `INTEGRATION_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. RFC-0032 phone-as-swarm-worker. Host TTS/SAPI (RFC-0092). RFC-0109 media pipelines (attachments may queue; analyze happens on Leader). HexStrike. Persona merge. Committing model weights.

## Notes

- Source: Taco high-impact add 2026-09-17. Number **0108** (after 0107 Obsidian).
- Linux cloud cannot sign off on-device GGUF load. Implement unit-tests the routing/sync; physical Android is sign-off.
- Implement launch: this RFC only; branch from `development`; do not edit Architect spec docs; PR against `development`; do not merge other PRs. Android companion lane owns `android/` (see `.cursor/agents/jarvis-android-companion.md`); do not casually rewrite `backend/app/auth.py` or inference hotswap.
