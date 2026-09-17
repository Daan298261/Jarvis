# Jarvis Integration Specs

**Status:** living architect priority list for third-party / reel-sourced integrations  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

This file is the Architect priority list for **Instagram Saved → jarvis** reel integrations and Taco’s high-impact adds that were not in the original reel RFC set. It does **not** replace [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md) (architecture + queue) or [`docs/rfcs/`](docs/rfcs/) (one-ticket contracts). Implementers take **one** named RFC from this list. Product code is a follow-up ticket; this document and its RFCs are specs.

**Related (do not rewrite here):** [RFC-0095](docs/rfcs/0095-instagram-jarvis-collection-module-catalog.md) umbrella + Module Catalog **Download**. [`EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS.md`](EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS.md) / [`EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS_V2.md`](EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS_V2.md) (Obsidian ReferenceStore + Browser Use + OpenViking evaluation). [`ANDROID_CLIENT.md`](ANDROID_CLIENT.md) (phone is a Leader controller). [`JARVIS_2.0.md`](JARVIS_2.0.md) §76 multimedia / BlackGrid. Architect ledger: master plan **§59 Decision Log** only — no §57 rewrite, no new §58 checkbox.

**Jarvis 1.4.0 interesting set (not a reorder of this ladder):** RFC-**0107–0110** (Obsidian brain, phone offline model, media upload, ChatGPT-style approval modal — **0110 implemented**) are **in** the 1.4 cut together with core packages RFC-0111–0115 from [`JARVIS_1.4_SPECS.md`](JARVIS_1.4_SPECS.md) and HexStrike/Daybreak/cyber already in flight (0105 implemented, 0106 implemented). **Bulk catalog / reel children RFC-0095–0104 stay later** on this document — do not re-scope them into 1.4 RFCs or block the 1.4 cut. **RFC-0116 TypeSafe Jev** is a **post-1.4 optional accelerator** (below) — interesting, **not** blocking 1.4.0 unless Taco later says so.

**Hard rules for every row below:** full product intent; implement tickets ship the real surface, not a placeholder chip / health-only panel / “coming soon” path as the deliverable. Do **not** invent LE / Red / Purple / ATO gates in these tickets (owner later). Do **not** put exploit recipes, PoCs, payloads, or attack steps in specs or product help. Do **not** vendor third-party trees into Jarvis git. Do **not** merge `persona_candidate` assistants into butler/voice.

**Assignee lanes:** **D1** = backend / workers / inference / connectors. **UX** = Daybreak / portal / Android companion chrome. A row may name both; the named implement ticket still does **one** RFC.

---

## Local clone libraries (not in git)

Architect mines Taco Instagram `@tacotcr` Saved → **jarvis** offline. Clones live in the owner library, **not** in this repository.

| Role | Path |
| --- | --- |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\` |
| Architect / cloud library | `/workspace/projects/` |

Typical layout (RFC-0095 Download destinations): `…/rfc/<slug>`, `…/persona/<name>`, `…/le-gated/<slug>`, plus RFC-0095 Desktop `%USERPROFILE%\Desktop\projects\<slug>`. Re-fetch uses Module Catalog Download; do not commit clones.

---

## Priority ladder (Taco)

Quick / highest impact first. Numbers **0107–0109** are the Taco priority pack (tip’s latest reel/cyber RFC was **0106**). **0110** is a related owner-chat UX contract (below) — it does **not** bump 0108/0109. Reel children keep their reserved numbers; this list **reorders them by impact**, it does not renumber them.

### 1. Obsidian as linked memory / durable brain — NEW (strengthened)

Jarvis treats an owner Obsidian vault **plus** the existing DB/cache (RFC-0011 ContextRepo + memory) as the **external durable brain**. Large durable context — persona packs, tools catalogs, history dumps — must **not** live in every inference prompt. Immediate `n_keep ≥ n_ctx` 400 band-aids are a **separate** inference ticket; this row’s end-state is **external store + on-demand retrieval**, not “compress forever.”

Canonical human-readable knowledge lives as plain Markdown in the vault (wiki-links + graph). Jarvis indexes, watches, caches, and writes managed notes with provenance, in sync with structured memory. When the owner says “open the project note,” “follow that link,” “add this decision to the vault,” or “what did we decide about X,” Jarvis resolves wiki-links / backlinks, reads a hop-capped graph neighborhood, and either answers with vault provenance or mutates a note the way a human in Obsidian would. OpenViking/RAGFlow (RFC-0099) may index the same files as a sidecar; Markdown on disk stays canonical. This is not a second orchestrator and not TTS.

**On each user ask** (any ask; this ticket does not invent LE/Red/Purple/ATO gates): a quick **internal search** over **installed and installable** tools that aid **that** task, then pull only the matched schemas/docs into the turn. Do **not** pre-stuff the context window with the whole catalog. Installable-but-missing hits use a real RFC-0090 / RFC-0095 install path — not a soft-fail empty chip.

**RFC:** [`docs/rfcs/0107-obsidian-linked-memory-brain.md`](docs/rfcs/0107-obsidian-linked-memory-brain.md). **Status:** accepted (specs-only; full intent, no stubs). **Local clone:** optional pattern source `Rob-Morris/obsidian-brain` under `/workspace/projects/` or `C:\Users\daanv\projects\jarvis-ig\` if Architect clones it; vault itself is the owner’s Obsidian folder (not a reel repo). **Lane:** D1 (watch/index/sync/act-on-links + per-turn working-set/tool search) + UX (vault picker, health, broken-link repair).

### 2. Phone companion offline AI model — NEW / extend Android companion

The Android companion must keep working when the Windows Leader is unreachable: a **local on-device model** on the phone answers chat and bounded commands offline. When the PC is online, **PC Jarvis remains the orchestrator** — the phone is still a paired controller (RFC-0039 / RFC-0059 / `ANDROID_CLIENT.md`); it does not become a second brain, a swarm `PHONE` node, or a silent stub that only queues “send later.” Offline turns run on the device model, persist locally, and **sync** to Leader conversations/outbox when the session returns. Online turns prefer Leader 9B/27B; the phone model may stay as a low-latency front-end (align RFC-0035) but must not replace host TTS/STT defaults (RFC-0092). **RFC:** [`docs/rfcs/0108-phone-companion-offline-ai-model.md`](docs/rfcs/0108-phone-companion-offline-ai-model.md). **Status:** accepted (specs-only). **Local clone:** none required (extends `android/`). **Lane:** D1 (on-device runtime + sync contract) + UX (companion model status, download, offline banner).

### 3. Media / file / video upload on phone + PC apps — NEW

Owners must **upload media, files, and videos** from both the **Android companion** and the **Desktop / portal** into Jarvis for **analyze**, **edit**, and **Black Grid / media pipelines**. Companion today has a thin attachment POST (`/api/companion/attachments`, 64 MiB) plus gallery/camera/share; Daybreak/portal Chat has **no** composer attach. This ticket makes typed ingest real on **both** surfaces: progress, size/type policy, durable artifacts (RFC-0021), and handoff into BlackGrid `image` / `video` / `timeline` / `stitch` (RFC-0096 / 0097) and analyze tools — not a chip that never reaches a worker. **RFC:** [`docs/rfcs/0109-media-file-video-upload-phone-and-pc.md`](docs/rfcs/0109-media-file-video-upload-phone-and-pc.md). **Status:** accepted (specs-only). **Local clone:** none (product surfaces). **Lane:** UX (composer + Android attach/studio) + D1 (ingest API, artifact store, pipeline handoff).

### Related UX contract — RFC-0110 ChatGPT-style approval / review popup — NEW

Not a fourth integration clone and **not** a reorder of 0107–0109. Owner chat gets a ChatGPT-like **modal only when the model/tool flow actually needs a decision or typed input**: **Always allow** / **Allow this time** / **Deny**, plus optional (or required) free-text. **Always allow** persists per tool/action class so repeats do not re-prompt. Ordinary daily chat stays **ungated** and **streams** — this is explicitly **not** the old always-on “Review or approval is required” bar on conversation. Extends RFC-0079 computer-use catalog chrome; does not invent LE/Red/Purple gates; no exploit recipes. Full intent, no stubs/soft-fail. **RFC:** [`docs/rfcs/0110-chatgpt-style-approval-popup.md`](docs/rfcs/0110-chatgpt-style-approval-popup.md). **Status:** **implemented** on `development` (specs [#284](https://github.com/Daan298261/Jarvis/pull/284), grants API [#288](https://github.com/Daan298261/Jarvis/pull/288), UI [#290](https://github.com/Daan298261/Jarvis/pull/290)). Live HUD modal + spoken grants is Windows desktop sign-off. **Lane:** UX (modal + idle HUD copy, landed) + D1 (grant store, park/resume only for real decisions, landed).

### Related optional accelerator — RFC-0116 TypeSafe Jev (System One) decision tier — NEW

Not a clone, **not** a reorder of 0107–0109, and **not** in the 1.4.0 cut. TypeSafe **Jev** is an optional cloud **decision accelerator** (classify / route / score / branch; typed schema; calibrated confidence) for Jarvis control-path decisions: RFC-0107 per-turn tool select, RFC-0075 speak class, RFC-0115 complexity/escalate, RFC-0110 approval-needed, optional tool-intent guardrail. Local Ornith + heuristics stay default. **Jev is early access / waitlist** as of 2026-09-17 — specs land now; **implement is gated** on public/early-access API availability **and** owner opt-in. Settings: waitlist/status + “notify when ready”; **no fake-live stubs** (no local LLM pretending to be Jev). Packaging: free owner toggle (`jev_optional`) plus Plus entitlement (`decision.jev_plus` via real `has_feature` / `/api/license/entitlements`, not `if True`) when billing exists. No invented LE/Red/Purple gates. Full intent, no stubs/soft-fail. **RFC:** [`docs/rfcs/0116-typesafe-jev-optional-decision-tier.md`](docs/rfcs/0116-typesafe-jev-optional-decision-tier.md). **Status:** accepted (specs-only; post-1.4 optional). **Local clone:** none (hosted TypeSafe API). **Lane:** D1 (client, probe, entitlement, control-path wire) + UX (Models & Inference Decision tier + audit log).

---

## Umbrella — RFC-0095 Module Catalog + Download

**Instagram jarvis collection ingest + Module Catalog Download.** Every Saved→jarvis candidate follows Download → usefulness review → integrate decision → implement. Packs / Module Catalog **Download** clones or zips to Desktop/`projects` or the library roots above (allowlisted `source_url` only). Full-assistant repos are `persona_candidate` (no butler merge). This umbrella does **not** implement children. **RFC:** [`docs/rfcs/0095-instagram-jarvis-collection-module-catalog.md`](docs/rfcs/0095-instagram-jarvis-collection-module-catalog.md). **Status:** accepted (specs-only; implement is a named follow-up). **Local clone:** library roots above (do not commit). **Lane:** D1 (catalog API + download job) + UX (Packs / Module Catalog Download + Open folder).

---

## Reel RFCs (impact order)

Impact order is Taco’s ladder, **not** numeric order. Status is the RFC file plus what already landed on `development` as of 2026-09-17. Do not invent authorization gates on these rows.

### RFC-0098 — Browser-Use deepen

Jarvis already has a partial Browser Use worker; Playwright stays the **default** browser tool. Deepen the existing adapter (session reuse, structured results, observability, RFC-0090 Install now) so unfamiliar-site discovery is a real optional worker, not a “package missing” dead end. Do not replace Playwright, do not make Browser Use the primary app, do not vendor `browser-use/browser-use`. **RFC:** [`docs/rfcs/0098-browser-use-deepen.md`](docs/rfcs/0098-browser-use-deepen.md). **Status:** accepted RFC; backend deepen landed on `development` via [#273](https://github.com/Daan298261/Jarvis/pull/273) (`f109347`). Live Browser Use remains Windows desktop sign-off. **Local clone:** `/workspace/projects/rfc/browser-use` · `C:\Users\daanv\projects\jarvis-ig\rfc\browser-use`. **Lane:** D1.

### RFC-0101 — Pipecat realtime voice pipeline

Optional Pipecat transport / VAD / turn-taking **behind** existing Jarvis STT/TTS/persona. Conversation state stays Jarvis-owned. **Do not rewrite RFC-0092** (Kokoro default, no silent SAPI). Speak filter (RFC-0075) still runs before audio frames. Missing Pipecat leaves clip STT/TTS and companion duplex (RFC-0064) working. **RFC:** [`docs/rfcs/0101-pipecat-realtime-voice-pipeline.md`](docs/rfcs/0101-pipecat-realtime-voice-pipeline.md). **Status:** accepted (specs-only). **Local clone:** `/workspace/projects/rfc/pipecat` · `C:\Users\daanv\projects\jarvis-ig\rfc\pipecat`. **Lane:** D1.

### RFC-0096 — ComfyUI + SANA BlackGrid media gen

BlackGrid `image` / `video` connector to owner-installed ComfyUI (optional SANA / Ref2VA-VSA). Jarvis stays orchestrator; sidecars are HTTP/workflow APIs, not a second portal. `studio_capabilities()` is truthful: available only when the sidecar is reachable — never advertise a placeholder generator. GPU load/unload per `JARVIS_2.0.md` §76; outputs are artifacts. **RFC:** [`docs/rfcs/0096-comfyui-sana-blackgrid-media-gen.md`](docs/rfcs/0096-comfyui-sana-blackgrid-media-gen.md). **Status:** accepted (specs-only). **Local clone:** `/workspace/projects/rfc/{comfyui,sana,comfyui-ref2va-vsa}` · same under `C:\Users\daanv\projects\jarvis-ig\rfc\`. **Lane:** D1.

### RFC-0097 — OpenCut / OpenMontage / Hyperframes stitch

BlackGrid `timeline` / `stitch` connectors (OpenCut primary; OpenMontage / Hyperframes optional) plus optional Real-ESRGAN **preprocess** (passthrough on failure; not a generator). Not a second NLE inside the Jarvis portal. **RFC:** [`docs/rfcs/0097-opencut-openmontage-hyperframes-blackgrid-stitch.md`](docs/rfcs/0097-opencut-openmontage-hyperframes-blackgrid-stitch.md). **Status:** accepted (specs-only). **Local clone:** `/workspace/projects/rfc/{opencut,openmontage,hyperframes,real-esrgan}` · same under `jarvis-ig\rfc\`. **Lane:** D1.

### RFC-0099 — OpenViking / RAGFlow memory

Optional context/RAG sidecars. **OpenViking is agent memory / hierarchical context — not TTS.** Jarvis DB + ContextRepo stay canonical; disabling sidecars leaves native memory working. Do not vendor AGPL. Complements RFC-0107 (Obsidian Markdown is the human vault; OpenViking may index it). **RFC:** [`docs/rfcs/0099-openviking-ragflow-memory.md`](docs/rfcs/0099-openviking-ragflow-memory.md). **Status:** accepted (specs-only). **Local clone:** `/workspace/projects/rfc/{openviking,ragflow}` · same under `jarvis-ig\rfc\`. **Lane:** D1.

### RFC-0100 — Firecrawl / Crawl4AI research

Policy-bounded research crawl connectors beside `web_fetch` / ingest. Host / depth / page caps; same network gate as `INTERNET_TOOLS`. Not unrestricted WAN scrape. Missing sidecar degrades to `web_fetch` / Playwright. **RFC:** [`docs/rfcs/0100-firecrawl-crawl4ai-research.md`](docs/rfcs/0100-firecrawl-crawl4ai-research.md). **Status:** accepted (specs-only). **Local clone:** `/workspace/projects/rfc/{firecrawl,crawl4ai}` · same under `jarvis-ig\rfc\`. **Lane:** D1.

### RFC-0103 — RuView Wi‑Fi home presence

Commodity Wi‑Fi CSI → household occupancy / ambient observations (`HOME_IOT` / RFC-0053). Privacy: no raw CSI in chat/logs by default. **Not HexStrike. Not RFC-0069 HUD / `PresenceHost`.** Missing RuView leaves perception/IoT unchanged. **RFC:** [`docs/rfcs/0103-ruview-wifi-home-presence.md`](docs/rfcs/0103-ruview-wifi-home-presence.md). **Status:** accepted (specs-only). **Local clone:** `/workspace/projects/rfc/ruview` · `C:\Users\daanv\projects\jarvis-ig\rfc\ruview`. **Lane:** D1.

### RFC-0102 — LocalSend LAN share

Nearby send/receive of owner-approved files on the home LAN (interop with LocalSend clients). Receive asks; send respects filesystem allowlist. **Not** a swarm node and **not** a Guest Portal replacement. Complements RFC-0109 (upload into Jarvis) — LocalSend moves bytes between devices; 0109 ingests into analyze/studio. **RFC:** [`docs/rfcs/0102-localsend-lan-share.md`](docs/rfcs/0102-localsend-lan-share.md). **Status:** accepted (specs-only). **Local clone:** `/workspace/projects/rfc/localsend` · `C:\Users\daanv\projects\jarvis-ig\rfc\localsend`. **Lane:** D1 + UX (Settings Network).

### RFC-0104 — Persona candidates pack (later)

Tag-only hold for full AI-assistant / harness repos (hermes-agent, openhuman, F.R.I.D.A.Y, deer-flow, openclaude, opencode, locally-uncensored). **No butler / voice / system-prompt merge.** Download ≠ integrate. Personality track is a later named RFC after Taco promotes it. **RFC:** [`docs/rfcs/0104-persona-candidates-pack.md`](docs/rfcs/0104-persona-candidates-pack.md). **Status:** accepted hold (not an implement ticket now). **Local clone:** `/workspace/projects/persona/<name>` · `C:\Users\daanv\projects\jarvis-ig\persona\<name>`. **Lane:** later (Architect / UX catalog badges only until promoted).

### RFC-0105 — Cybersecurity module

One Module Catalog pack `cybersecurity` with six Instagram clones (Strix, Anthropic Cybersecurity Skills, Exploitarium, Pentagi, Claude-Red, Flowsint) as **partial** connectors on **Daybreak** (enable / status / path / open-folder / Download). HexStrike stays a **sibling** suite (RFC-0078 / 0086 / 0106) — do not collapse. This row does **not** invent LE/ATO gates and does **not** document exploits. **RFC:** [`docs/rfcs/0105-cybersecurity-module.md`](docs/rfcs/0105-cybersecurity-module.md). **Status:** **implemented** on `development` (specs [#272](https://github.com/Daan298261/Jarvis/pull/272), Daybreak UI [#274](https://github.com/Daan298261/Jarvis/pull/274), backend hooks [#277](https://github.com/Daan298261/Jarvis/pull/277)). Live HUD / Open folder / subprocess is Windows desktop sign-off. **Local clone:** `/workspace/projects/le-gated/<slug>` · `C:\Users\daanv\projects\jarvis-ig\le-gated\<slug>`. **Lane:** UX (Daybreak, landed) + D1 (worker hooks, landed).

### RFC-0106 — HexStrike Daybreak operator

Jarvis **is** the HexStrike operator: Daybreak HUD + owner chat drive the **full** upstream operator surface (install/repair, discovered toolchain, MCP and/or operator HTTP, jobs/logs/artifacts), not a health-only shell and not the RFC-0086 five-enum ceiling. Loopback bind + pinned install stay. RFC-0105 remains a sibling. No invented LE/Red/Purple/ATO gates in this ticket. No exploit recipes in specs, help, or tests. **RFC:** [`docs/rfcs/0106-hexstrike-jarvis-full-operator-control.md`](docs/rfcs/0106-hexstrike-jarvis-full-operator-control.md). **Status:** **implemented** on `development` (specs [#276](https://github.com/Daan298261/Jarvis/pull/276), backend [#279](https://github.com/Daan298261/Jarvis/pull/279), Daybreak UX [#283](https://github.com/Daan298261/Jarvis/pull/283)). Live pinned install / HUD+chat invoke is Windows desktop sign-off. **Local clone:** managed pin `runtime/hexstrike-ai` (not git-vendored); upstream https://github.com/0x4m4/hexstrike-ai. **Lane:** D1 (landed) + UX (Daybreak `HudHexStrikeSuite`, landed).

---

## Numbering

| RFC | Title | Notes |
| --- | --- | --- |
| 0095 | Instagram collection + Module Catalog Download | Umbrella |
| 0096–0104 | Reel children | Reserved by RFC-0095 / PR #271 |
| 0105 | Cybersecurity module | Implemented |
| 0106 | HexStrike full operator control | Implemented |
| **0107** | Obsidian linked memory / durable brain | Taco add — vault/graph + DB/cache; per-turn tool search; not compress-forever; **in 1.4 interesting set** |
| **0108** | Phone companion offline AI model | Taco add — same priority pack / ladder; **in 1.4 interesting set** |
| **0109** | Media/file/video upload (phone + PC) | Taco add — same priority pack / ladder; **in 1.4 interesting set** |
| **0110** | ChatGPT-style approval / review popup | **Implemented** — Always / Allow this time / Deny + persist + free-text; **not** always-on chat gate; **in 1.4 interesting set** |
| **0111–0115** | 1.4 core (Kokoro runtime, voice preview, Settings IA deltas, context recovery, Ornith router) | Not integration clones — see [`JARVIS_1.4_SPECS.md`](JARVIS_1.4_SPECS.md). **0095–0104 bulk catalog remains later / out of 1.4 cut.** |
| **0116** | TypeSafe Jev optional decision tier | Post-1.4 **optional accelerator** — waitlist-gated; does **not** block 1.4.0 |

If a later tip already occupied 0107+, Architect takes the next free numbers. **0107–0109** landed as specs on `development` via [#280](https://github.com/Daan298261/Jarvis/pull/280). Next free after 0109 was **0110**. **0111–0115** are the 1.4 spec split (not Instagram children). **0116** is the next free after 0115 (Taco 2026-09-17 Jev add).

---

## Out of scope for this document

Product implementation. Instagram scraping in product code. Vendoring clones. Persona merge. Invented authorization / LE gates. Exploit/PoC/payload documentation. Swarm / P4–P5 / model-stack except where a named RFC already says so (0108 is a **companion** on-device model, not P4 swarm routing). Architect rewrites of `SECURITY_AGENTS.md` / `ANDROID_CLIENT.md` / `PORTAL_UX.md` / `JARVIS_2.0.md` beyond the §59 ledger tick.
