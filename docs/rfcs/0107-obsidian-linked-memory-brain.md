# RFC-0107: Obsidian as linked memory / durable brain

**Status:** accepted (amended 2026-09-17 — Taco: embed the **real** Obsidian UI; operational brain, not décor. Stays `accepted` until UX embed + remaining backend land.)  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17  
**Updated:** 2026-09-17 (Taco follow-up: external brain + per-turn tool search; not compress-forever). **Amended:** 2026-09-17 (Taco: Obsidian must be **operational soon and actually used**; **do not** build a custom Obsidian/brain UI — **host the real Obsidian app UI inside Jarvis**).

**Parent / index:** [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) (Taco priority #1). Same ladder as RFC-0108 (phone offline) and RFC-0109 (media upload) — this RFC does not reorder them. Architect ledger: [`JARVIS_MASTER_PLAN.md`](../../JARVIS_MASTER_PLAN.md) **§59 Decision Log** pointer only.  
**Related (do not rewrite):** RFC-0011 context repositories + consolidation (DB remains authoritative for structured facts). RFC-0013 compact harness / on-demand tools (compaction is a **band-aid**, not this RFC’s end-state). RFC-0020 project knowledge workspaces. RFC-0028 off-context journal. RFC-0060 docs-first grounding. RFC-0061 persona pack (TTS/personality path stays; the **full pack must not be stuffed into every inference prompt**). RFC-0077 hotswap keeps a **short** identity working set, not the whole dump. RFC-0085 universal fast path (expose only tools the turn needs). RFC-0090 Install now. RFC-0095 Module Catalog (installable packs). RFC-0099 OpenViking/RAGFlow (**sidecar RAG — not TTS**; Markdown stays canonical). RFC-0110 ChatGPT-style approval popup (sibling UX; not this ticket). RFC-0114 overflow recovery (separate; not this end-state). [RFC-0122](0122-ingress-size-gate-spill-and-trajectory-cap.md) optional vault spill of oversized **ingress** blobs (hybrid: DB authoritative for the turn payload; vault is a durable mirror — **do not replace this RFC**). `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS.md` SPEC-REFERENCE-OBSIDIAN-001. `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS_V2.md` §11 Obsidian Brain. Windows Desktop shell: Tauri 2 + WebView2 (`frontend/src-tauri`, `com.jarvis.desktop`); Electron is an `ARCHITECTURE.md` alternative, not the current shell.

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not vendor Obsidian, Obsidian Brain, or owner vaults into Jarvis git. Full intent; **no stubs / soft-fail** (a bound path whose retrieval always returns empty; a “catalog saved” chip that still serializes every tool into the prompt; a custom note list that pretends to be Obsidian; or a host pane that only “Open in external Obsidian” without an in-Jarvis Obsidian UI, is a fail).

**Landed vs remaining:** vault bind / watch / lexical index / graph resolve / managed-note act / per-turn working-set + tool search backend is on `development` via [#295](https://github.com/Daan298261/Jarvis/pull/295). That is **necessary, not sufficient**. This amend does **not** mark the RFC implemented. Remaining: **embedded real Obsidian UI** + proving the bound vault is **used** on owner turns (reads/writes/wiki-links/graph, not décor).

## Problem

Three failures share one cause: **durable knowledge is treated as prompt furniture or as a fake in-app notebook**.

1. **No owner linked brain (or a bound vault that is never used).** Jarvis memory is SQLite structured facts plus a versioned ContextRepo (`backend/app/memory/`, `backend/app/api/memory.py`, `backend/app/api/context_repo.py`). That is agent-owned state. It is **not** the owner’s linked notebook unless Jarvis **actually** reads, writes, and follows wiki-links in a bound vault. Inspiration and vault conventions exist in `Rob-Morris/obsidian-brain` and in the External Agent Infra specs. None of that was a named implementable RFC, so workers either ignore the vault or bolt OpenViking on as a second authority (RFC-0099 forbids dual memory authority; RFC-0092 forbids OpenViking-as-TTS). A vault picker with empty retrieval is décor.

2. **Every inference prompt is stuffed.** Persona packs, the full tools catalog, and history dumps are pushed into `n_ctx` on ordinary turns. Immediate llama.cpp `n_keep ≥ n_ctx` HTTP 400 band-aids are **fixed elsewhere** (RFC-0114 / inference ticket — not this RFC). Compressing the overflowing prompt “forever” is not the product. Without this RFC’s end-state, “graph-as-memory” dies as a slide and the context window stays a junk drawer.

3. **A custom “Jarvis brain” UI would be the wrong product.** Rebuilding a note browser, markdown editor, backlink pane, or graph viewer in React **is not Obsidian**. The owner already lives in Obsidian (editor, graph, wiki-links, plugins, CSS, daily notes). Taco 2026-09-17: **do not build that clone.** Host the **real Obsidian UI inside Jarvis** so the owner can see and edit the same vault the agent uses.

Taco’s high-impact add (kept): **Obsidian as Jarvis’s linked memory / durable brain**, plus **on-demand internal tool search on every owner ask**.  
Taco’s UI/ops amend (this revision): that brain must be **operational soon and actually used**, and the owner surface is the **embedded real Obsidian app**, not a parallel Jarvis notebook.

## Decision

Implement an **external durable brain** that is **on the hot path**, a **per-turn working set**, and an **in-Jarvis host for the real Obsidian UI**. Jarvis remains the orchestrator.

| What | Rule |
| --- | --- |
| Canonical files | Plain Markdown + wiki-links on disk in the **bound owner vault**. |
| Structured / provenance | Existing Jarvis DB/cache (RFC-0011) — required. |
| Agent use | **Required.** Bind, watch, retrieve, follow links, write managed notes. Not optional décor. |
| Owner UI | **The real Obsidian app UI embedded inside Jarvis** (Desktop/portal host). |
| Obsidian process down | File watch/index/act against Markdown **still works**. That is **not** permission to ship a custom editor as the owner surface. |
| Missing Obsidian install | Real install / open CTA. **Not** a Jarvis-built note browser that “counts” as shipping. |

**Will not** treat `n_keep`, prompt truncation, or “fit_tools_to_context” as the destination. Those may remain emergency clamps. The implement ticket ships **external store + search + embedded Obsidian**, not a smarter compressor.

**Will not** invent LE / Red / Purple / ATO gates in this ticket. Owner asks of any kind run the same internal search. Execution still goes through existing RFC-0002 / RFC-0027 / RFC-0031 policy at tool-run time. Do **not** put exploit recipes, PoCs, or attack steps in vault templates, catalog blurbs, or help.

### End-state (this RFC)

| Layer | Lives | Enters the model |
| --- | --- | --- |
| Long-term human knowledge (notes, decisions, projects, manuals, persona source, catalogs, history dumps) | Owner vault graph + Jarvis DB/cache (RFC-0011 / ContextRepo / journal). Owner **sees and edits** that vault **inside Jarvis via real Obsidian**. | **Never as a whole.** Retrieved excerpts only. |
| Structured facts, permissions, provenance indexes | Jarvis DB (`backend/app/memory/`) — RFC-0011 | Pointers + the facts this turn actually needs |
| Installed + installable tools | Registry + Module Catalog / optional workers (RFC-0095 / RFC-0090) | **Search, then pull** the matched tool schemas/docs for **this** ask |
| Short conversational working set | Recent turns + compact identity/tone (not the full persona pack dump) | Yes, bounded |

### 1. Canonical ownership

| Layer | Authority |
| --- | --- |
| Structured facts, permissions, provenance indexes, tool-search cache | Jarvis DB (`backend/app/memory/`) — RFC-0011 |
| Human-readable linked knowledge (notes, decisions, project pages, manuals, durable persona source) | Owner vault Markdown (this RFC) |
| Owner-facing editor / graph / wiki-link navigation | **Official Obsidian UI**, hosted inside Jarvis (section 3). Not a Jarvis reimplementation. |
| Optional retrieval sidecar | OpenViking / RAGFlow (RFC-0099) **indexing the same files** — disable sidecar ⇒ vault + native memory still work |

Do **not** replace the FastAPI orchestrator, task state, or DB with Obsidian. Do **not** dump raw tool traces or chain-of-thought into the vault. Do **not** inject the whole vault, the whole persona pack, the whole tools catalog, or a history dump into a prompt.

### 2. Vault binding + agent use path (operational, not décor)

Owner picks a local folder (existing Obsidian vault, Jarvis-managed vault, or Obsidian Brain vault). Persist the path in settings (write-only; never echo secrets). Binding is the **on switch for the durable brain**, not a Settings souvenir: after bind, Jarvis **must** watch, index, retrieve, and write.

Default suggested Jarvis-managed layout (extensible; do not hard-code every category):

```text
<vault>/
  _Config/router.md
  _Config/Taxonomy/
  _Temporal/Sessions/
  Projects/
  Decisions/
  People/
  Systems/
  Sources/
  Home/
```

Recommended YAML frontmatter on Jarvis-managed notes: stable `id`, `type`, timestamps, `source`, `tags`, `sensitivity`, `jarvis_managed`, wiki-links to related notes. Owner-authored notes without frontmatter still index.

**Agent use path (required on owner turns that need durable context):**

| Direction | Behavior |
| --- | --- |
| **Read** | Lexical (required) + optional semantic search over the bound vault. Return path + heading + content hash + excerpt. |
| **Wiki-links** | Resolve `[[Note]]` and markdown links to a vault path + heading (rename-safe via `id` when present). |
| **Graph** | Retrieve the neighborhood (note + backlinks + N hops, capped) and **follow a link as the next retrieval step** when the ask needs it. |
| **Write** | Create / append / edit **managed** notes (`jarvis_managed: true`) with a pointer back to the memory/task id. Promote a verified task outcome into a living note when the owner (or policy) asks. |
| **Open for the owner** | Focus the same note **inside the embedded Obsidian UI** (official `obsidian://open?vault=…&file=…` / CLI), not in a Jarvis markdown pane. |
| **Sync** | Section 5 — vault ↔ RFC-0011 memory, provenance-preserving. |

**Fails (décor / stub):** bound path whose search always returns empty; binder that never watches; “brain connected” chrome with no vault hits in the turn working set when the ask is about vault content; writes that never land as files the embedded Obsidian can open.

Filesystem watch + incremental reindex: an Obsidian save (from the **embedded** UI or any other editor) becomes visible to Jarvis without restart. One-file edits must not reindex the whole vault.

### 3. Embedded Obsidian surface (owner UI — this amend)

**Product rule:** the owner opens **Obsidian inside Jarvis** and edits the bound vault there. Jarvis chrome around that surface is a **host**, not a second notebook.

#### 3a. What the owner sees

On **Windows Desktop** (required host) and in the **portal route that Desktop hosts**:

1. A first-class Jarvis destination (implementer names the route; e.g. Daybreak/portal **Obsidian** pane — **not** a takeover of `/memory` skills/trajectories).
2. That pane is filled by the **real Obsidian application UI**: editor, file/leaf chrome, wiki-link navigation, graph view, command palette, and the owner’s existing plugins/themes — whatever Obsidian itself shows for that vault.
3. Thin Jarvis chrome only: vault bind/unbind, missing-install CTA, bind/health/broken-link status, “focus this note.” No note list that replaces Obsidian’s file explorer. No Jarvis graph canvas.

**Acceptance (owner path):** bind a vault → open the Obsidian surface **inside Jarvis** → create or edit a note **in that Obsidian UI** → save → the file exists on disk in the bound vault → Jarvis watch/reindex sees it without restart → a later owner ask that needs that note retrieves it with provenance. Opening an **external** Obsidian window as the only shipped path is a **fail**. A screenshot, “coming soon,” or empty webview is a **fail**.

#### 3b. Host path (match Windows Desktop architecture)

Jarvis Desktop today is **Tauri 2 + WebView2** (`frontend/src-tauri`). Obsidian Desktop is its own Electron app. Official Obsidian surfaces to drive (do not invent a private protocol):

- URI: `obsidian://open?vault=…`, `obsidian://open?vault=…&file=…` (`paneType=tab|split|window` as needed).
- CLI (Obsidian 1.12+ installer, when enabled): `obsidian vault=…` / `vault:open` — launches the app if it is not running.
- Installed `Obsidian.exe` targeting the **bound vault path**.

**Implementer picks the first host that actually shows Obsidian’s own UI inside Jarvis:**

| Priority | Host | When |
| --- | --- | --- |
| 1 | **Official Obsidian embed / local-vault web renderer** documented by Obsidian at implement time | If it exists and can open the **local bound vault** (not Publish-only, not a third-party clone). Prefer this over Win32 hacks. |
| 2 | **Native host of installed Obsidian** inside the Jarvis Desktop window | **Default on current Tauri/WebView2 Windows Desktop:** extra Tauri window or WebView2/native pane whose client area parents the live `Obsidian.exe` HWND (child-window host). Launch/focus via URI/CLI against the bound vault. Resize/focus with the Jarvis pane. |
| 3 | **Electron `BrowserView` / webview** of the official Obsidian renderer | **Only if** the Desktop shell in use is Electron (`ARCHITECTURE.md` alternative). Do **not** add an Electron shell just to embed. |

Portal in a **plain browser** cannot HWND-embed `Obsidian.exe`. Desktop is the required embed host. Browser portal shows the same destination with **truthful** chrome (bind status + “Open Obsidian in Jarvis Desktop”) — **not** a custom markdown fallback that counts as shipping. If priority-1 official local-vault web embed exists, the browser portal **may** use it.

Android companion is **not** the Obsidian host (vault lives on the PC). Do not ship a phone note-clone.

#### 3c. Forbidden — parallel custom brain UI

Do **not** ship any of these as the Obsidian / brain surface (including as a “fallback that works in the browser”):

- Custom note browser / file tree that opens vault Markdown in Jarvis
- Custom markdown editor (CodeMirror / textarea / preview pane) for vault notes
- Custom graph / backlink viewer
- A “Jarvis brain” page that reimplements Obsidian navigation, wikilinks, or plugins
- Growing `/memory` (skills/trajectories) or ContextRepo into a vault explorer
- iframe of **Obsidian Publish** (cloud) as the owner’s local brain
- Community “Obsidian web” clones, headless-sync dashboards, or screenshot placeholders

Existing `/memory` **stays** the RFC-0011 skills/trajectories page. It is **not** the brain.

Missing Obsidian: detect, offer a **real** install/open path (RFC-0090-style CTA or the vendor installer). Soft-fail empty pane, or substituting a Jarvis editor, is a fail.

### 4. Graph-as-memory (act on links)

Wiki-links (`[[Note]]`, markdown links to vault files) and backlinks are a **graph**. Jarvis must:

1. **Resolve** a link to a vault path + heading (rename-safe via `id` when present).
2. **Retrieve** the neighborhood (note + backlinks + N hops, capped) with provenance (path, heading, content hash).
3. **Act:** open/read, create, append, or edit a managed note; follow a link as the next retrieval step; promote a verified task outcome into a living note when the owner (or policy) asks. **Open** means the embedded Obsidian UI focuses that note. User edits in Obsidian **win** over generated bodies; conflicts surface, they are not silently overwritten.
4. **Health/repair:** broken links, duplicate ids, stale generated indexes, missing router entries, invalid frontmatter. Repair rebuilds generated state; it does not rewrite user prose unless explicitly requested. Health is **status chrome**, not a substitute for the embed.

### 5. Sync with agent memory

Bidirectional, explicit, provenance-preserving:

- **Vault → Jarvis:** indexed excerpts become retrievable context (docs-first / ContextRepo search). High-impact facts may be proposed as RFC-0011 memory mutations (approval/verification unchanged; the **approval UI** is RFC-0110, not an always-on chat gate).
- **Jarvis → vault:** selected durable decisions/procedures/project pages are written as Markdown notes with `jarvis_managed: true` and a pointer back to the memory/task id. Those notes must open in the **embedded** Obsidian UI. Episodic chatter stays in DB/journal (RFC-0028), not the brain.
- **Cache:** lexical (required) + optional local semantic index over the same files. Cache is a speed layer, not a second authority. Invalidate on watch events.

Router.md is a compact orientation file for local models, not a dump of the vault.

### 6. Prompt working set (what *does* go to the model)

Each owner ask composes a **turn working set**, not “everything we might ever need”:

1. Compact identity / tone (short butler register retrieved from the pack/brain — **not** the full persona pack, few-shot dump, or tools essay).
2. The current user message + a **bounded** recent-turn tail (RFC-0077). Full conversation/history dumps stay in DB/journal/vault and are retrieved only when the ask needs them.
3. Vault / memory **hits for this ask** (hop-capped neighborhood, docs-first hits, RFC-0011 facts) with provenance. If the vault is bound and the ask is about vault/project/decision content, **hits must be present** — empty-by-construction is a fail.
4. **Tool schemas for this ask only** (section 7).

Acceptance tests must prove a turn prompt does **not** contain the unused remainder of the catalog, the unused remainder of the vault, or a pasted history dump.

### 7. Per-turn internal tool search (installed **or** installable)

**Kept** (do not drop). On **each** user ask (any ask; this ticket does not add a content filter on the search):

1. Run a **quick internal search** over:
   - **Installed** tools (`REGISTRY` / `backend/app/tools/exposure.py` / MCP advertised tools).
   - **Installable** tools and packs (Module Catalog / RFC-0095 Download destinations, RFC-0090 optional workers, documented connectors that exist but are not loaded yet).
2. Rank by fit to **this** task. Pull into the turn: name, short description, and the schema/docs needed to call or to offer install. Cap the pulled set (implementer picks a small hard cap; dumping the catalog “just in case” is a fail).
3. If a high-fit tool is **installable but not installed**, the turn may offer a real Install-now / Download path (RFC-0090 / RFC-0095). A decorative “tool exists somewhere” string with no catalog hit is a **fail**. A pre-stuffed full catalog so the model can “see everything” is a **fail**.
4. Search is **local/internal** (registry + catalog + vault/DB cache). It is not a WAN scrape of the internet for the catalog itself. RFC-0100 research crawl remains a separate ticket.
5. Static `TASK_TOOL_SETS` in `exposure.py` may seed the search; they are not a substitute for per-ask search, and they must not serialize the unused rest of `NATIVE_TOOLS` / MCP listings into the prompt.

`request_capability` stays available so the model can ask for a missing tool **after** search, not instead of search.

### 8. Pattern source (optional clone)

`Rob-Morris/obsidian-brain` (MIT) is the **pattern** source (router/taxonomy/living vs temporal). Extract conventions; do **not** vendor the runtime as a hard dependency. Optional later MCP adapter for an external Brain process; Jarvis **must** work against the Markdown files with that process down. RFC-0095 Download may clone it into the library; Download ≠ integrate.

**Architect’s initial recommendation:** native ReferenceStore + graph actions (`partial` / extract). Taco can override to `archive_only` on the Brain repo while still requiring vault binding + per-turn search + **embedded official Obsidian UI**.

**Will not:** vendor Obsidian or Brain; replace ContextRepo/DB; use OpenViking as TTS; merge persona packs into butler/voice; HexStrike; offensive tools; dump full vault/catalog/history into prompts; treat n_keep/compaction as the end-state; invent authorization gates; ship a stub indexer; **ship a custom Obsidian/brain UI**; treat Obsidian as optional décor.

## Acceptance criteria

Pipeline below is **spec’d** here; product code is the later named ticket (full intent, not a stub). Status stays **accepted** until these land.

- [ ] Specs-only in **this** amend PR (no `frontend/src` / backend product edits; no vault/clones committed)
- [ ] Owner can bind a local vault path; Jarvis watches Markdown and incrementally reindexes; DB/cache stays the structured/provenance layer (RFC-0011)
- [ ] **Operational use:** after bind, agent **reads** (search + wiki-link resolve + hop-capped neighborhood) and **writes** managed notes; a vault-relevant owner ask puts vault excerpts **with provenance** into the turn working set (empty-by-construction is a fail)
- [ ] Wiki-links / backlinks resolve; retrieval returns path + heading + hash; neighborhood is hop-capped
- [ ] Jarvis can create/update managed notes that open in the **embedded Obsidian UI** (and remain plain Markdown for any text editor)
- [ ] **Embedded Obsidian:** owner opens Obsidian **inside Jarvis** (Desktop/portal host) and **edits a vault note there**; save is a real file write; watch/reindex sees it without restart
- [ ] Host matches Windows Desktop: official embed if available, else Tauri/WebView2 native host of `Obsidian.exe`, else Electron `BrowserView` only if that is the shell — see §3b
- [ ] **Forbidden UIs absent:** no custom note browser, custom graph viewer, or “Jarvis brain” clone; `/memory` is not turned into a vault explorer
- [ ] Missing Obsidian install surfaces a real install/open CTA, not a Jarvis editor fallback
- [ ] User vault edits (including from the embedded UI) win; conflicts surface; broken-link health exists as chrome, not as the product
- [ ] Sync with RFC-0011 memory is explicit + provenanced; disabling RFC-0099 sidecars leaves vault + native memory working
- [ ] Orchestrator never injects the full vault, full persona pack, full tools catalog, or a history dump into an inference prompt
- [ ] Every owner ask runs an internal search over **installed and installable** tools and pulls only the matched working set into that turn (cap enforced)
- [ ] Installable-but-missing high-fit tools surface a real install/download path, not a soft-fail empty catalog
- [ ] Tests prove unused catalog/vault/history bytes are absent from the serialized prompt; tests prove search hits both an installed tool and an installable-uninstalled pack; tests prove a vault-relevant ask includes vault provenance
- [ ] This RFC’s implement ticket is **not** closed by an `n_keep` / 400 / truncation-only change, **nor** by backend bind/index without the embed, **nor** by “open external Obsidian” only
- [ ] Light §59 Decision Log line only
- [ ] Implement follow-up: `python3 -m pytest`; if portal/Desktop host touched, `npm --prefix frontend run build` (and lint if TS changed). Live Obsidian.exe embed + large vault is **Windows desktop sign-off**.

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | existing `backend/app/memory/obsidian_vault.py`, `backend/app/api/vault.py` (bind, watch, index, graph resolve, health, act — landed #295; extend if embed host needs status/URI helpers); `backend/app/memory/repository.py` / `backend/app/memory/store.py` sync hooks; `backend/app/api/memory.py` + `backend/app/api/context_repo.py`; settings path persistence; `backend/app/agent/turn_working_set.py` / `tool_retrieval.py` (`fit_tools_to_context` remains a clamp, not the design). **Do not** add a Markdown-preview API as the owner UI. |
| Desktop host (implement PR only) | `frontend/src-tauri/` (Tauri 2 window / WebView2 / native HWND host of official Obsidian); `frontend/src/desktop/bridge.ts` invoke for launch/focus/embed. Electron `BrowserView` **only** if the shell is Electron. |
| Frontend (implement PR only) | **New** host pane/route for the embedded Obsidian surface (Daybreak/portal). Thin bind/health chrome. **Do not** implement a note browser in `frontend/src/pages/Memory.tsx` or `ContextRepo.tsx`. `/memory` stays skills/trajectories. Settings knowledge/integrations: bind path + deep-link to the host pane. |
| Tests | `tests/test_rfc0107_*.py` — keep link resolve, incremental index, user-edit wins, sidecar-off, **no full-vault/catalog/history inject**, per-ask installed + installable search; add vault-relevant working-set provenance; host-bridge unit tests where they do not need Obsidian.exe. Live embed = desktop sign-off. |
| Docs | this RFC; `INTEGRATION_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. Vendoring Obsidian/Brain. RFC-0099 implement. RFC-0092 voice. Persona merge (RFC-0104). HexStrike / RFC-0105 / RFC-0106. Swarm. Instagram scraper. Committing owner vaults. The `n_keep ≥ n_ctx` 400 inference band-aid (RFC-0114). RFC-0108 phone offline model. RFC-0109 media upload. RFC-0110 approval popup chrome (cite only; do not implement here). Invented LE/Red/Purple/ATO gates. Exploit/PoC/payload documentation. Android companion Obsidian embed. Building a custom Obsidian clone “until Desktop is ready.”

## Notes

- Source: Taco high-impact add 2026-09-17 (not in the original reel reserved list). Tip latest was RFC-0106; this number is **0107**. Same-day follow-up: durable context out of the prompt; search tools per ask; end-state is external brain, not compress-forever. **Same-day amend:** Obsidian operational soon **and actually used**; **embed the real Obsidian UI** inside Jarvis; **no** custom brain UI.
- Linux cloud can unit-test a temp vault + watch fixtures + prompt-composition assertions. Live Obsidian app embed + large vault is Windows desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
