# RFC-0107: Obsidian as linked memory / durable brain

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17  
**Updated:** 2026-09-17 (Taco follow-up: external brain + per-turn tool search; not compress-forever)

**Parent / index:** [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) (Taco priority #1). Same ladder as RFC-0108 (phone offline) and RFC-0109 (media upload) — this RFC does not reorder them.  
**Related (do not rewrite):** RFC-0011 context repositories + consolidation (DB remains authoritative for structured facts). RFC-0013 compact harness / on-demand tools (compaction is a **band-aid**, not this RFC’s end-state). RFC-0020 project knowledge workspaces. RFC-0028 off-context journal. RFC-0060 docs-first grounding. RFC-0061 persona pack (TTS/personality path stays; the **full pack must not be stuffed into every inference prompt**). RFC-0077 hotswap keeps a **short** identity working set, not the whole dump. RFC-0085 universal fast path (expose only tools the turn needs). RFC-0090 Install now. RFC-0095 Module Catalog (installable packs). RFC-0099 OpenViking/RAGFlow (**sidecar RAG — not TTS**; Markdown stays canonical). RFC-0110 ChatGPT-style approval popup (sibling UX; not this ticket). `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS.md` SPEC-REFERENCE-OBSIDIAN-001. `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS_V2.md` §11 Obsidian Brain.

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not vendor Obsidian, Obsidian Brain, or owner vaults into Jarvis git. Full intent; **no stubs / soft-fail** (a bound path whose retrieval always returns empty, or a “catalog saved” chip that still serializes every tool into the prompt, is a fail).

## Problem

Two failures share one cause: **durable knowledge is treated as prompt furniture**.

1. **No owner linked brain.** Jarvis memory today is SQLite structured facts plus a versioned ContextRepo (`backend/app/memory/`, `backend/app/api/memory.py`, `backend/app/api/context_repo.py`). That is agent-owned state. It is **not** the owner’s linked notebook: no wiki-links, no graph neighborhood, no “open this note and act on the linked project,” no live sync with an Obsidian vault the owner already lives in. Inspiration and vault conventions exist in `Rob-Morris/obsidian-brain` and in the External Agent Infra specs. None of that was a named implementable RFC, so workers either ignore the vault or bolt OpenViking on as a second authority (RFC-0099 forbids dual memory authority; RFC-0092 forbids OpenViking-as-TTS).

2. **Every inference prompt is stuffed.** Persona packs, the full tools catalog, and history dumps are pushed into `n_ctx` on ordinary turns. That is the wrong architecture. Immediate llama.cpp `n_keep ≥ n_ctx` HTTP 400 band-aids are **fixed elsewhere** (inference/session ticket — not this RFC). Compressing the overflowing prompt “forever” is not the product. Without this RFC’s end-state, “graph-as-memory” dies as a slide and the context window stays a junk drawer.

Taco’s high-impact add: **Obsidian as Jarvis’s linked memory / durable brain**, plus **on-demand internal tool search on every owner ask**.

## Decision

Implement an **external durable brain** and a **per-turn working set**. Jarvis remains the orchestrator. Obsidian (the app) is optional; **plain Markdown + wiki-links on disk** plus the **existing Jarvis DB/cache** are required.

### End-state (this RFC)

| Layer | Lives | Enters the model |
| --- | --- | --- |
| Long-term human knowledge (notes, decisions, projects, manuals, persona source, catalogs, history dumps) | Owner vault graph + Jarvis DB/cache (RFC-0011 / ContextRepo / journal) | **Never as a whole.** Retrieved excerpts only. |
| Structured facts, permissions, provenance indexes | Jarvis DB (`backend/app/memory/`) — RFC-0011 | Pointers + the facts this turn actually needs |
| Installed + installable tools | Registry + Module Catalog / optional workers (RFC-0095 / RFC-0090) | **Search, then pull** the matched tool schemas/docs for **this** ask |
| Short conversational working set | Recent turns + compact identity/tone (not the full persona pack dump) | Yes, bounded |

**Will not** treat `n_keep`, prompt truncation, or “fit_tools_to_context” as the destination. Those may remain emergency clamps. The implement ticket ships **external store + search**, not a smarter compressor.

**Will not** invent LE / Red / Purple / ATO gates in this ticket. Owner asks of any kind run the same internal search. Execution still goes through existing RFC-0002 / RFC-0027 / RFC-0031 policy at tool-run time. Do **not** put exploit recipes, PoCs, or attack steps in vault templates, catalog blurbs, or help.

### 1. Canonical ownership

| Layer | Authority |
| --- | --- |
| Structured facts, permissions, provenance indexes, tool-search cache | Jarvis DB (`backend/app/memory/`) — RFC-0011 |
| Human-readable linked knowledge (notes, decisions, project pages, manuals, durable persona source) | Owner vault Markdown (this RFC) |
| Optional retrieval sidecar | OpenViking / RAGFlow (RFC-0099) **indexing the same files** — disable sidecar ⇒ vault + native memory still work |

Do **not** replace the FastAPI orchestrator, task state, or DB with Obsidian. Do **not** dump raw tool traces or chain-of-thought into the vault. Do **not** inject the whole vault, the whole persona pack, the whole tools catalog, or a history dump into a prompt.

### 2. Vault binding

Owner picks a local folder (existing Obsidian vault, Jarvis-managed vault, or Obsidian Brain vault). Persist the path in settings (write-only; never echo secrets). Default suggested Jarvis-managed layout (extensible; do not hard-code every category):

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

### 3. Graph-as-memory (act on links)

Wiki-links (`[[Note]]`, markdown links to vault files) and backlinks are a **graph**. Jarvis must:

1. **Resolve** a link to a vault path + heading (rename-safe via `id` when present).
2. **Retrieve** the neighborhood (note + backlinks + N hops, capped) with provenance (path, heading, content hash).
3. **Act:** open/read, create, append, or edit a managed note; follow a link as the next retrieval step; promote a verified task outcome into a living note when the owner (or policy) asks. User edits in Obsidian **win** over generated bodies; conflicts surface, they are not silently overwritten.
4. **Health/repair:** broken links, duplicate ids, stale generated indexes, missing router entries, invalid frontmatter. Repair rebuilds generated state; it does not rewrite user prose unless explicitly requested.

Filesystem watch + incremental reindex: an Obsidian save becomes visible to Jarvis without restart. One-file edits must not reindex the whole vault.

### 4. Sync with agent memory

Bidirectional, explicit, provenance-preserving:

- **Vault → Jarvis:** indexed excerpts become retrievable context (docs-first / ContextRepo search). High-impact facts may be proposed as RFC-0011 memory mutations (approval/verification unchanged; the **approval UI** is RFC-0110, not an always-on chat gate).
- **Jarvis → vault:** selected durable decisions/procedures/project pages are written as Markdown notes with `jarvis_managed: true` and a pointer back to the memory/task id. Episodic chatter stays in DB/journal (RFC-0028), not the brain.
- **Cache:** lexical (required) + optional local semantic index over the same files. Cache is a speed layer, not a second authority. Invalidate on watch events.

Router.md is a compact orientation file for local models, not a dump of the vault.

### 5. Prompt working set (what *does* go to the model)

Each owner ask composes a **turn working set**, not “everything we might ever need”:

1. Compact identity / tone (short butler register retrieved from the pack/brain — **not** the full persona pack, few-shot dump, or tools essay).
2. The current user message + a **bounded** recent-turn tail (RFC-0077). Full conversation/history dumps stay in DB/journal/vault and are retrieved only when the ask needs them.
3. Vault / memory **hits for this ask** (hop-capped neighborhood, docs-first hits, RFC-0011 facts) with provenance.
4. **Tool schemas for this ask only** (section 6).

Acceptance tests must prove a turn prompt does **not** contain the unused remainder of the catalog, the unused remainder of the vault, or a pasted history dump.

### 6. Per-turn internal tool search (installed **or** installable)

On **each** user ask (any ask; this ticket does not add a content filter on the search):

1. Run a **quick internal search** over:
   - **Installed** tools (`REGISTRY` / `backend/app/tools/exposure.py` / MCP advertised tools).
   - **Installable** tools and packs (Module Catalog / RFC-0095 Download destinations, RFC-0090 optional workers, documented connectors that exist but are not loaded yet).
2. Rank by fit to **this** task. Pull into the turn: name, short description, and the schema/docs needed to call or to offer install. Cap the pulled set (implementer picks a small hard cap; dumping the catalog “just in case” is a fail).
3. If a high-fit tool is **installable but not installed**, the turn may offer a real Install-now / Download path (RFC-0090 / RFC-0095). A decorative “tool exists somewhere” string with no catalog hit is a **fail**. A pre-stuffed full catalog so the model can “see everything” is a **fail**.
4. Search is **local/internal** (registry + catalog + vault/DB cache). It is not a WAN scrape of the internet for the catalog itself. RFC-0100 research crawl remains a separate ticket.
5. Static `TASK_TOOL_SETS` in `exposure.py` may seed the search; they are not a substitute for per-ask search, and they must not serialize the unused rest of `NATIVE_TOOLS` / MCP listings into the prompt.

`request_capability` stays available so the model can ask for a missing tool **after** search, not instead of search.

### 7. Pattern source (optional clone)

`Rob-Morris/obsidian-brain` (MIT) is the **pattern** source (router/taxonomy/living vs temporal). Extract conventions; do **not** vendor the runtime as a hard dependency. Optional later MCP adapter for an external Brain process; Jarvis **must** work against the Markdown files with that process down. RFC-0095 Download may clone it into the library; Download ≠ integrate.

**Architect’s initial recommendation:** native ReferenceStore + graph actions (`partial` / extract). Taco can override to `archive_only` on the Brain repo while still requiring vault binding + per-turn search.

**Will not:** vendor Obsidian or Brain; replace ContextRepo/DB; use OpenViking as TTS; merge persona packs into butler/voice; HexStrike; offensive tools; dump full vault/catalog/history into prompts; treat n_keep/compaction as the end-state; invent authorization gates; ship a stub indexer.

## Acceptance criteria

Pipeline below is **spec’d** here; product code is the later named ticket (full intent, not a stub).

- [ ] Specs-only in this PR (no `frontend/src` / backend product edits; no vault/clones committed)
- [ ] Owner can bind a local vault path; Jarvis watches Markdown and incrementally reindexes; DB/cache stays the structured/provenance layer (RFC-0011)
- [ ] Wiki-links / backlinks resolve; retrieval returns path + heading + hash; neighborhood is hop-capped
- [ ] Jarvis can create/update managed notes that open in Obsidian and any text editor
- [ ] User vault edits win; conflicts surface; broken-link health exists
- [ ] Sync with RFC-0011 memory is explicit + provenanced; disabling RFC-0099 sidecars leaves vault + native memory working
- [ ] Orchestrator never injects the full vault, full persona pack, full tools catalog, or a history dump into an inference prompt
- [ ] Every owner ask runs an internal search over **installed and installable** tools and pulls only the matched working set into that turn (cap enforced)
- [ ] Installable-but-missing high-fit tools surface a real install/download path, not a soft-fail empty catalog
- [ ] Tests prove unused catalog/vault/history bytes are absent from the serialized prompt; tests prove search hits both an installed tool and an installable-uninstalled pack
- [ ] This RFC’s implement ticket is **not** closed by an `n_keep` / 400 / truncation-only change
- [ ] Light §59 Decision Log line only (via `INTEGRATION_SPECS.md` batch)
- [ ] Implement follow-up: `python3 -m pytest`; if portal touched, `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | new `backend/app/memory/obsidian_vault.py` (or `backend/app/context/obsidian.py`) — bind, watch, index, graph resolve, health; `backend/app/memory/repository.py` / `backend/app/memory/store.py` sync hooks; `backend/app/api/memory.py` + `backend/app/api/context_repo.py` vault search/act endpoints; settings path persistence; new per-turn composer (working set) beside `backend/app/tools/exposure.py`, `backend/app/tools/registry.py`, `backend/app/api/tools.py`, `backend/app/persona/pack.py`, `backend/app/inference/manager.py` (`fit_tools_to_context` remains a clamp, not the design) |
| Frontend (implement PR only) | `frontend/src/pages/Memory.tsx`, `ContextRepo.tsx` — vault picker, health, broken links; Settings knowledge/integrations deep-link; not a full Obsidian clone UI |
| Tests | `tests/test_rfc0107_*.py` — link resolve, incremental index, user-edit wins, sidecar-off still works, **no full-vault/catalog/history inject**, per-ask installed + installable search |
| Docs | this RFC; `INTEGRATION_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. Vendoring Obsidian/Brain. RFC-0099 implement. RFC-0092 voice. Persona merge (RFC-0104). HexStrike / RFC-0105 / RFC-0106. Swarm. Instagram scraper. Committing owner vaults. The `n_keep ≥ n_ctx` 400 inference band-aid (separate ticket). RFC-0108 phone offline model. RFC-0109 media upload. RFC-0110 approval popup chrome (cite only; do not implement here). Invented LE/Red/Purple/ATO gates. Exploit/PoC/payload documentation.

## Notes

- Source: Taco high-impact add 2026-09-17 (not in the original reel reserved list). Tip latest was RFC-0106; this number is **0107**. Follow-up the same day: durable context out of the prompt; search tools per ask; end-state is external brain, not compress-forever.
- Linux cloud can unit-test a temp vault + watch fixtures + prompt-composition assertions. Live Obsidian app + large vault is Windows desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
