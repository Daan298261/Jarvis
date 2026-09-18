# RFC-0108: Phone companion offline AI model

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; D2 pack-cache / post-pair popup is a follow-up after this amend lands)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17  
**Amended:** 2026-09-18 (Taco via CoS — HOLD lifted for this slice: allowlisted pack URL, Leader packaging cache, first-up background download, post-pair popup)

**Parent / index:** [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) (Taco priority #2).  
**Related (do not rewrite):** RFC-0039 Android native client (Leader remains authoritative **when reachable**). RFC-0059 companion delivery (implemented). RFC-0064 / RFC-0066 realtime voice. RFC-0074 pairing + QR. RFC-0076 APK delivery UX. RFC-0032 ultra-low-bit / edge routing (**optional ephemeral worker is not this ticket**). RFC-0035 tiny command front-end (host-side; this RFC is **on-device**). RFC-0092 neural TTS default (**do not rewrite**; phone TTS/STT stay as today unless 0092 already landed). [`RFC-0123`](0123-companion-reachability-and-anti-impersonation.md) companion reachability + anti-impersonation (sibling; do not invent LE/Red/Purple gates). `ANDROID_CLIENT.md` (phone is a controller, not P3 swarm). `docs/android-companion.md`.

**#309 implement contract (do not weaken):** D1 [#309](https://github.com/Daan298261/Jarvis/pull/309) already landed llama.cpp JNI, `CompanionPackManager`, online/offline routing, `OutboxQueue`, `GET /api/companion/model-packs`, `POST /api/companion/sync/offline-turns`, and `DevicePackChromePublisher` (`MISSING` / `DOWNLOADING` / `READY` / `RUNNING` / `ERROR`). This amend **extends** that contract (pinned download path + Leader cache + post-pair offer). It does **not** replace the runtime, routing, Outbox, or sync.

This PR is **specs-only**. Product code is the next D2 implement ticket after this land. Do not put GGUF weights in git. A catalog row with **no download path** is a **fail**.

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

1. **Runtime:** in-process engine capable of GGUF (or equivalent documented mobile format) on CPU / NPU / GPU as the device allows. **v1 engine is llama.cpp JNI** (`LlamaCppInferenceEngine` / native `jarvis_llama`) already used in the ecosystem. One engine in v1; do not leave the runtime unspecified.
2. **Weights:** **not** in git. Owner downloads a **phone-sized** instruct GGUF (order: 1B–3B class first; larger only if the device reports enough RAM). Catalog is a **pinned allowlist** of filenames **and fetch URLs** (plus hashes / `size_bytes`) **or** a Leader-mediated pack served from that same allowlist after the Leader has cached the file. **Never** an arbitrary URL the owner or model types. Progress is visible; failure is recoverable; missing weights show **install**, not a fake chat. Empty `url` / placeholder-only catalog rows are a **fail**.
3. **Quality bar:** offline chat must return model tokens on a device with the pack installed. Mock completions, canned strings, or “model coming soon” as the shipped path are **fails**.
4. **Resources:** respect thermal/battery; do not keep a 27B-class host profile on the phone; do not evict companion UX to load a giant model. If the device cannot load the selected pack, refuse with an actionable reason (RAM/storage), do not crash-loop.

Phone STT/TTS stay the existing companion paths (clip / RFC-0064 WSS when online). This RFC does **not** change host RFC-0092 defaults. Offline TTS may use the existing on-device Android speech APIs for playback of local replies; it must not reintroduce silent SAPI on the **PC**. Fine-tune of the phone pack is **out of scope** for this amend (later ticket OK).

### 2.1 Pinned allowlist (required download path)

Keep the **#309 catalog ids** (do not rename or drop them):

| id | Role | Allowlisted fetch URL (pinned; implement must not leave `url=""`) |
| --- | --- | --- |
| `qwen2.5-1.5b-instruct-q4` | **Recommended** phone-sized pack (1.5B Q4_K_M) | `https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| `qwen2.5-3b-instruct-q4` | Optional larger phone pack (3B Q4_K_M) | `https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf` |

Local `filename` stays the #309 names (`Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` / `Qwen2.5-3B-Instruct-Q4_K_M.gguf`) even if the remote object uses lowercase. Catalog `size_bytes` must match the pinned object (or the Leader’s measured length after cache); the post-pair popup shows **size in MB** from that figure (`size_bytes / 1_000_000`, rounded, e.g. **~1120 MB** for the official 1.5B Q4_K_M). Implement **must** pin the real SHA-256 of each allowlisted object (all-zero / blank hash on the recommended pack is a **fail**).

Fetch **only** those pinned URLs (HTTPS GET of the allowlisted object). No owner-typed URL, no model-scraped URL, no second CDN unless Architect adds it to this table. A later pin bump is an Architect catalog edit, not a runtime allow-any.

Phone download order after pairing (full path, not metadata-only):

1. If the Leader packaging cache has the selected pack **and** the session is live → paired device pulls bytes from the Leader (`GET /api/companion/model-packs/{id}/file` or equivalent; device auth required; path-bound to the cached file).
2. Else HTTPS GET of the **pinned** catalog URL into app-private `files/model-packs/` (existing `CompanionPackManager`).

`GET /api/companion/model-packs` remains the metadata catalog (engine, packs[].id/filename/url/sha256/size_bytes/recommended). Metadata **without** a usable fetch (empty `url` **and** no Leader-cached file) is a **fail**.

### 2.2 Leader packaging cache (gitignore weights)

The Leader **does** keep a **packaging copy** of the recommended pack for companion/catalog — this is **not** on-device inference on the PC and does **not** make the phone a second brain.

- **On-disk path:** `data/companion-packs/<filename>` (under the existing gitignored `data/` tree). Optional mirror under `models/companion/` is also gitignored via `models/`.
- **Never commit** `*.gguf`, `*.gguf.partial`, or other weight binaries. Repo `.gitignore` must list those patterns explicitly (belt-and-suspenders on top of `data/` / `models/`).
- Catalog JSON in git is URLs + hashes + sizes only.
- The cache is for (a) local packaging / APK-adjacent distribution and (b) serving the paired phone over the companion TLS gateway ([RFC-0123](0123-companion-reachability-and-anti-impersonation.md) `:4781`). It is **not** a public file server and **not** an unauthenticated download.

### 2.3 First Leader-up background download

The **first time** this Jarvis Leader process is up (fresh install or first boot after this feature lands), start a **background** download of the **recommended** allowlisted pack into `data/companion-packs/`.

- **Non-blocking:** owner chat, pairing, Play, and inference must not wait on the pack. Failure to cache must not crash the Leader.
- **Observable progress:** bytes done / `size_bytes`, state `idle` / `downloading` / `ready` / `error`, last error. Surface on Phone / companion pairing page and `GET /api/companion/model-packs` (or a sibling status field). Resume partial files (`.gguf.partial`) across restarts.
- Download **only** the pinned URL. Verify SHA-256 before renaming to the final filename. Corrupt/partial files stay `error` + retry, not `ready`.
- Subsequent Leader starts: if the recommended file is already `ready` (hash-ok), do not re-fetch. Optional 3B pack is **not** auto-downloaded on first up (owner/Models can still request it).

### 2.4 Post-pair popup (phone)

**After pairing completes** (owner confirms fingerprint + phone session is `active` — existing RFC-0074 / RFC-0063 / RFC-0059 path), the **phone** shows a **popup** offering to download the **recommended** offline model pack **to the phone**.

- Copy names the pack and shows **size in MB** (from catalog `size_bytes`, e.g. “Download Qwen2.5 1.5B Instruct (Q4_K_M) for offline chat — **~1120 MB**”).
- Actions: **Download** (starts `CompanionPackManager` / DevicePackChrome `DOWNLOADING`) or **Not now** (dismiss; More / Models still has Download later).
- If the pack is already `ready` on the phone, do not nag.
- If Leader cache is `ready`, prefer the Leader-mediated file (LAN). If Leader cache is still downloading, the popup may say the PC is fetching it and still offer Download (phone can use the pinned URL, or wait — implement picks one honest path; silent no-op is a **fail**).
- Fine-tune / extra packs / “always download on pair” policy are later. This amend is the one-shot offer + size.

Pairing itself must not require the GGUF (existing rule). RFC-0123 pairing-key / TLS rules are unchanged by this popup.

### 3. What offline may and must not do

**May (v1):** local Q&A against the on-device model; read last-synced conversation/task snapshot cached on device; compose a message/attachment into Outbox; capture camera/gallery for later Leader analyze (RFC-0109); show honest connectivity (“Leader unreachable — answering on-device”).

**Must not (v1):** start HexStrike / RFC-0105 tools; mutate Leader filesystem; claim BlackGrid gen is running on the phone; become a swarm Node / RFC-0032 ephemeral worker (that remains a separate enrollment). Tool-using work **queues for the Leader**.

Pairing, Keystore identity, TLS pins, and revocation (RFC-0059 / 0074) stay required for **online** mode. Offline mode does not weaken pairing when the Leader returns.

### 4. Surfaces

- Companion **More / Models**: status (`missing` / `downloading` / `ready` / `running` / `error`), selected pack, storage used, **Download**, delete pack. (#309 chrome contract — keep.)
- Chat: offline banner + local stream; when Leader returns, banner clears and sync runs.
- **Post-pair popup** on the phone (§2.4) with pack size in MB.
- Desktop pairing / Phone page: Leader cache progress (first-up background download) plus the existing pack hint. Pairing does not block on GGUF. WAN / port-forward / relay stay RFC-0123.

**Architect’s initial recommendation:** `partial` — on-device runtime inside the existing companion, Leader orchestrator online. Taco can override pack size / engine, not the online-orchestrator rule.

**Will not:** second Jarvis on the phone; vendor weights; P3 swarm phone role; rewrite RFC-0092; persona merge; HexStrike-on-device; invented LE gates.

## Acceptance criteria

- [ ] Specs-only in this PR (no `android/` / `frontend/src` / backend product edits; no GGUFs committed)
- [ ] Online: Leader remains orchestrator; companion stays the paired controller
- [ ] Offline: on-device model produces real tokens when the pack is installed; no canned-stub deliverable
- [ ] Queued turns sync to Leader with stable ids; no second memory authority
- [ ] Pack download/progress/delete; missing pack is installable, not a fake chat
- [ ] **#309 contract kept:** llama.cpp JNI, routing, Outbox, `GET /api/companion/model-packs`, `POST /api/companion/sync/offline-turns`, DevicePackChrome statuses — this amend does not strip them
- [ ] Catalog **recommended** pack has a **pinned allowlisted URL** (table in §2.1); empty `url` is a **fail**; no arbitrary URL fetch
- [ ] Leader first-up **background** download of the recommended pack into `data/companion-packs/` (non-blocking; progress observable; hash-verified)
- [ ] Weights **gitignored** (`*.gguf` / `*.gguf.partial` / data tree); never committed
- [ ] After pairing completes, phone **popup** offers offline-pack download with **size in MB**; Download starts a real fetch (Leader cache or pinned URL)
- [ ] Not a swarm `PHONE` node; not HexStrike-on-phone
- [ ] RFC-0092 / host TTS defaults not rewritten here; fine-tune out of scope
- [ ] Light §59 Decision Log line only; RFC-0123 is the security sibling (do not invent LE/Red/Purple gates)
- [ ] Implement follow-up (D2 after this land): fill catalog URLs + Leader cache job + post-pair popup; Android unit tests + `python3 -m pytest` for catalog-not-empty-url / cache status / sync; live token generation remains **device sign-off** (cloud VM cannot)

## Likely files

| Area | Paths |
| --- | --- |
| Android (D2 implement PR only) | `CompanionPackCatalog.kt` / `CompanionPackManager.kt` — fill pinned URLs; post-pair popup after session `active`; keep `files/model-packs/` + DevicePackChrome. Do **not** rewrite JNI / Outbox / routing. |
| Backend (D2 implement PR only) | `backend/app/mobile/companion_offline.py` — real allowlisted `url` + sha256 + size; cache dir `data/companion-packs/`; first-up background fetch; paired `GET .../model-packs/{id}/file`; keep `/sync/offline-turns`. Startup hook (non-blocking). |
| Frontend (D2 implement PR only) | Phone / pairing page: Leader cache progress. Popup is **on the phone**; desktop may mirror status only. |
| Tests | Keep `tests/test_rfc0108_companion_sync.py`; add catalog URL non-empty + cache-status tests. Android: popup shown once after pair; size MB from `size_bytes`. |
| Docs | this RFC; [RFC-0123](0123-companion-reachability-and-anti-impersonation.md); `JARVIS_MASTER_PLAN.md` §59 only; `.gitignore` `*.gguf` |

## Out of scope

Product implementation in this PR. RFC-0032 phone-as-swarm-worker. Host TTS/SAPI (RFC-0092). RFC-0109 media pipelines (attachments may queue; analyze happens on Leader). HexStrike. Persona merge. Committing model weights. Fine-tune of the phone GGUF. RFC-0122 (parallel; do not take that number). Invented LE/Red/Purple gates.

## Notes

- Source: Taco high-impact add 2026-09-17. Number **0108** (after 0107 Obsidian). Amend 2026-09-18: Taco via CoS HOLD lift for allowlisted pack + Leader cache + first-up download + post-pair size popup.
- D1 [#309](https://github.com/Daan298261/Jarvis/pull/309) landed the runtime/routing/Outbox/sync contract on `development`. This amend is the **next D2 ticket after land** — do not reopen #309 to weaken it.
- Linux cloud cannot sign off on-device GGUF load. Implement unit-tests the routing/sync/catalog URL/cache job; physical Android is sign-off.
- Cross-link: companion port listen / pairing keys / anti-impersonation live in [RFC-0123](0123-companion-reachability-and-anti-impersonation.md) (`:4781`). Offline model does not change those rules.
- Implement launch (D2): this RFC only for the pack-cache/popup slice; branch from `development`; do not edit Architect spec docs in the implement PR; PR against `development`; do not merge other PRs. Android companion lane owns `android/` (see `.cursor/agents/jarvis-android-companion.md`); do not casually rewrite `backend/app/auth.py` or inference hotswap.
