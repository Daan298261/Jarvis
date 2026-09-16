# RFC-0095: Instagram Jarvis collection ingest pipeline + module catalog Download

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Related (do not rewrite):** RFC-0007 domain/workspace packs. RFC-0009 runtime portability. RFC-0020 project knowledge workspaces. RFC-0021 artifact crafts. RFC-0024 skill lifecycle. RFC-0047 portable automation packages. RFC-0058 Apex media parity. RFC-0059 BlackGrid capability contract. RFC-0069 presence catalog (RuView is a later connector, not a rewrite). RFC-0078 / RFC-0086 HexStrike + ATO (**do not** add offensive tools). RFC-0090 optional-worker Install now (git/pip allowlist pattern to reuse). `JARVIS_2.0.md` §76 multimedia. `SECURITY_AGENTS.md` §3.4 LE gate.

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not edit `frontend/src/` or backend in this PR. Local clones belong under Architect’s `projects/` library (on Architect’s box: `/workspace/projects`) — **not** committed here.

## Problem

Taco saves UI/repo inspiration on Instagram (`@tacotcr` Saved → **jarvis** collection, ~140 items). There is no systematic path from those saves into Jarvis **modules / skills / DLCs**: no Jarvis-managed local library of clones, no Architect/CoS usefulness review, no integrate-vs-archive decision, and no downloadable module packs for the owner.

Inspiration currently dies in Instagram. Optional workers (RFC-0090) can install five allowlisted backends; Packs (`/packs`, RFC-0007) install signed manifests. Neither is a catalog of third-party GitHub/local archives with a **Download** control that lands a clone or zip on Desktop/`projects`. BlackGrid Multimedia Studio remains a stub (`studio_capabilities()` `available: False`). Full-AI-assistant repos that look like personality sources have no `persona_candidate` tag, so they risk being merged into butler voice/persona by accident. Offensive/pentest saves (Strix, Pentagi, Claude-Red, Exploitarium, …) have no LE/archive rule, so an ordinary executing bot could try to wire them into product tools.

## Decision

Add an **umbrella ingest pipeline** for every Instagram-jarvis candidate, plus a **Module Catalog Download** control. This RFC does **not** implement any candidate. Child tickets (reserved below) do one integration each after Architect/CoS score and decide.

### 1. Four-step pipeline (every candidate)

Every collection item follows the same phases. Skipping a step is a fail.

1. **Download** — shallow-clone or archive the linked GitHub (or other VCS) repo into a Jarvis-managed local library. Default library root: `projects/` beside the Jarvis tree (Architect box: `/workspace/projects`). Cache/metadata may live under `data/module-cache/`. Do not vendor third-party trees into the Jarvis git repo. Do not commit clones in this PR.
2. **Usefulness review** — Architect/CoS score exactly one primary bucket (secondary tags allowed):
   - `mas_integration` — MAS / connector into existing Jarvis tools/workers
   - `skill` — reusable skill / pack resource
   - `module` — enableable module / DLC pack
   - `dlc` — downloadable content pack (specialist/domain)
   - `black_grid_media` — BlackGrid Multimedia Studio connector
   - `persona` — personality / full-assistant inspiration (`persona_candidate`)
   - `skip` — noise, duplicate, license-blocked, or not Jarvis
3. **Integrate decision** — `whole` (first-class worker/module), `partial` (connector/skill/adapter only), or `archive_only` (keep the clone; no product wiring). Offensive/pentest defaults to `archive_only` (see §3).
4. **Implement** — named RFC or §58 queue item **after** the decision. Ordinary cloud workers do not start swarm / P4–P5 / model-stack work from a save alone.

Pipeline state is durable per catalog entry (`download` → `review` → `decide` → `implement` / `skipped`). Re-saves of the same canonical repo dedupe; they do not fork a second clone.

### 2. Module Catalog + Download button

On **Packs** (`/packs`) **or** a new **Module Catalog** page (prefer extending Packs if the list stays small; split if Instagram-scale clutter would bury RFC-0007 install/preview), each catalog entry that has a linked GitHub URL **or** a local archive shows **Download**.

**Download** means: clone (`git clone --depth 1`) **or** fetch a zip/tarball into the owner destination. Default destination: Windows Desktop `projects` (`%USERPROFILE%\Desktop\projects\<slug>`). Alternate: the Jarvis-managed library (`projects/<slug>`). Owner may pick clone vs zip. Progress is observable; failure is recoverable (partial dir cleaned or marked `error`). Success records `local_path`, source URL, resolved commit/tag, and timestamp.

This is **not** RFC-0007 pack install (no unsigned code execution, no resource apply). This is **not** RFC-0090 “Install now” into Jarvis’s Python. After Download, the entry is library-local only until step 3 says otherwise.

**API (light; implement may rename, not invent a second catalog):**

| Method | Path | Intent |
| --- | --- | --- |
| `GET` | `/api/modules/catalog` | List entries: id, name, source_url, local_path, tags, review bucket, integrate decision, pipeline stage, `downloadable` |
| `GET` | `/api/modules/catalog/{id}` | One entry + provenance |
| `POST` | `/api/modules/catalog/{id}/download` | `{ "mode": "clone" \| "zip", "dest": "desktop_projects" \| "library" }` → job id; poll until `ready` / `error` |
| `GET` | `/api/modules/jobs/{job_id}` | Download progress (reuse optional-worker job overlay pattern from RFC-0090) |

Allowlist remotes the same way RFC-0090 / HexStrike install pin git URLs: catalog `source_url` only; refuse owner-typed arbitrary remotes in v1. Zip extraction must not escape the destination slug directory.

**UI (light):** one **Download** control per downloadable row; disabled + reason when `le_gated` and the LE/ATO gate is off; “Open folder” when `local_path` exists. Reuse Packs export/`downloadJson` only for **pack manifests**; repo Download is a separate action (clone/zip to disk).

Pack/portability reuse: RFC-0007 trust + preview before any later *install* of a Jarvis pack derived from a clone; RFC-0047 if the candidate becomes an automation package; RFC-0009 if an Agent Profile is part of a DLC. Download itself does not activate packs, skills, or workers.

### 3. Tags and gates

**`persona_candidate`** — full AI-assistant / personality-framework repos (hermes-agent, openhuman, F.R.I.D.A.Y, deer-flow, openclaude, opencode, locally-uncensored, and peers). Tag only. **No persona merge** in this RFC and no child until a later **personality pack** track. Do not fold them into RFC-0055 butler policy, RFC-0061/0062/0070/0092 voice, or default system prompt.

**`le_gated` / archive-only** — offensive / pentest / red / exploit frameworks (Strix, Pentagi, Claude-Red, Exploitarium, and peers). Ordinary Jarvis executing bots **must not** integrate them as tools, MCP servers, skills, or workers. Keep clones **archive-only**. Product wiring is **PolitieGPT / LE gate only** (`SECURITY_AGENTS.md` §3.4; RFC-0086 ATO). Purple is not a back door. Attempts to register offensive tools refuse + audit. HexStrike stays the existing defensive/read-only suite (RFC-0078 / 0086); this catalog does not widen it.

### 4. Black Grid media studio (this umbrella + reserved children)

`JARVIS_2.0.md` §76 and RFC-0059 already require BlackGrid (or equivalent) as a worker; companion `studio_capabilities()` advertises `projects / image / video / audio / takes / timeline / stitch / artifacts` with `available: False`. This umbrella names the **connector candidates**; it does not connect them.

| Track | Candidates | Role |
| --- | --- | --- |
| Image / videogen | ComfyUI, SANA | Local gen backends for BlackGrid `image` / `video` |
| Video stitch | OpenCut, OpenMontage, Hyperframes | Timeline / stitch for BlackGrid `timeline` / `stitch` |
| Restore | Real-ESRGAN | Upscale/restore pass before export |

Child RFC numbers are reserved in Notes. Do not implement media backends here. Do not advertise the placeholder as an operational generator (RFC-0059).

**Will not:** scrape Instagram in product code (Architect mines Saved → jarvis offline). Vendor upstream trees into Jarvis. Merge personas. Integrate offensive tools. Rewrite HexStrike, packs, or voice. Start child integrations in this PR.

## Acceptance criteria

- [ ] Specs-only in this PR (no `frontend/src` / backend product edits; no `projects/` clones committed)
- [ ] Four-step pipeline specified: Download → usefulness review → integrate decision → implement
- [ ] Module Catalog / Packs **Download** specified (clone or zip to Desktop/`projects` or library); API + UI light; reuse packs/portability/RFC-0090 job overlay, not pack-install
- [ ] Full-assistant entries tagged `persona_candidate`; no persona merge
- [ ] Offensive/pentest entries `le_gated` + `archive_only`; ordinary bots must not integrate (PolitieGPT/LE only)
- [ ] Black Grid media studio called out (ComfyUI/SANA, OpenCut/OpenMontage/Hyperframes, Real-ESRGAN) with child RFC numbers reserved
- [ ] Light §59 Decision Log line only (no §57 rewrite, no new §58 checkbox)
- [ ] Implement follow-up (separate ticket): `python3 -m pytest`; if portal touched, `npm --prefix frontend run build` (and lint if TS changed)

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/api/modules.py` (new) or extend `backend/app/api/packs.py`; `backend/app/modules/` catalog + download job; reuse `backend/app/workers/install.py` clone/job overlay; pin dest under Desktop/`projects` + library `projects/` |
| Frontend (implement PR only) | `frontend/src/pages/Packs.tsx` and/or new Module Catalog page; `frontend/src/App.tsx` route if split; `frontend/src/api.ts` |
| Tests | `tests/test_rfc0095_*.py` — allowlisted URL, dest sandbox, LE download disabled, zip path-escape refused |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 Decision Log line only |

## Out of scope

Product implementation in this PR. Instagram API/scraper. Child integrations (ComfyUI, video stitch, Browser-Use deepen, OpenViking/RAGFlow, Firecrawl/Crawl4AI, Pipecat, LocalSend, RuView, persona pack). Offensive tool registry. HexStrike redesign. Voice/TTS/persona merge. Architect rewrites of `JARVIS_2.0.md` / `SECURITY_AGENTS.md` / `PORTAL_UX.md` beyond the §59 ledger tick. Committing `/workspace/projects` clones.

## Notes

- Source: Taco Instagram `@tacotcr` Saved → **jarvis** (~140 items), Architect triage 2026-09-17. High-value subset only in this umbrella; the rest stay in the Architect library until scored.
- Local clones: Architect box `/workspace/projects` (not in this PR). Owner Download default: Desktop/`projects`.
- Linux cloud VMs can unit-test allowlist + dest sandbox. Live git clone / Desktop path is Windows desktop sign-off.
- Implement launch: implement this RFC only (catalog + Download); branch from `development`; pytest + frontend build; do not edit Architect spec docs; PR against `development`; do not merge other PRs.

### Reserved child RFC numbers (do not write in this PR)

| RFC | Child | Notes |
| --- | --- | --- |
| **0096** | ComfyUI + media gen module | ComfyUI + SANA; BlackGrid `image`/`video` connector; `black_grid_media` |
| **0097** | OpenCut / OpenMontage / Hyperframes video stitch | BlackGrid `timeline`/`stitch`; not a generator |
| **0098** | Browser-Use deepen | Deepen existing adapter (`browser-use/browser-use`); Playwright stays default; RFC-0019/0090 remain |
| **0099** | OpenViking / RAGFlow memory | Context/memory connector; not TTS (RFC-0092). OpenViking = context FS; RAGFlow = RAG engine |
| **0100** | Firecrawl / Crawl4AI research | Research crawl connectors; policy-bounded; not unrestricted WAN scrape |
| **0101** | Pipecat realtime voice | Realtime voice pipeline candidate; do **not** fold RFC-0092/0075 |
| **0102** | LocalSend LAN | Local device send/receive; companion/LAN, not swarm |
| **0103** | RuView presence | Presence/visual candidate; extend RFC-0069 catalog, do not fork `PresenceHost` |
| **0104** | Personality pack track | `persona_candidate` only until then: hermes-agent, openhuman, F.R.I.D.A.Y, deer-flow, openclaude, opencode, locally-uncensored |

Further collection items (skills, DLC, skip, LE archive) get later numbers after 0104. Offensive names stay in the catalog as `le_gated` + `archive_only` without a product RFC unless PolitieGPT/Taco names one.

### High-value child names (follow-up RFCs; Architect scores first)

- ComfyUI + media gen module
- OpenCut/OpenMontage/Hyperframes video stitch (Black Grid)
- Browser-Use deepen
- OpenViking / RAGFlow memory
- Firecrawl/Crawl4AI research
- Pipecat realtime voice
- LocalSend LAN
- RuView presence
- Persona candidates: hermes-agent, openhuman, F.R.I.D.A.Y, deer-flow, openclaude, opencode, locally-uncensored
