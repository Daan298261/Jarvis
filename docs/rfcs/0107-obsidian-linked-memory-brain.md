# RFC-0107: Obsidian as linked memory / brain

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent / index:** [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) (Taco priority #1).  
**Related (do not rewrite):** RFC-0011 context repositories + consolidation (DB remains authoritative for structured facts). RFC-0020 project knowledge workspaces. RFC-0028 off-context journal. RFC-0060 docs-first grounding. RFC-0099 OpenViking/RAGFlow (**sidecar RAG — not TTS**; Markdown stays canonical). `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS.md` SPEC-REFERENCE-OBSIDIAN-001. `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS_V2.md` §11 Obsidian Brain. RFC-0095 Module Catalog (optional clone of pattern repos only).

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not vendor Obsidian, Obsidian Brain, or owner vaults into Jarvis git.

## Problem

Jarvis memory today is SQLite structured facts plus a versioned ContextRepo (`backend/app/memory/`, `backend/app/api/memory.py`, `backend/app/api/context_repo.py`). That is agent-owned state. It is **not** the owner’s linked notebook: no wiki-links, no graph neighborhood, no “open this note and act on the linked project,” no live sync with an Obsidian vault the owner already lives in.

Taco’s high-impact add: **Obsidian as Jarvis’s linked memory / brain**. Inspiration and vault conventions exist in `Rob-Morris/obsidian-brain` and in the External Agent Infra specs (router, taxonomy, living vs temporal artifacts). None of that is a named implementable RFC, so workers either ignore the vault or would bolt OpenViking on as a second authority (RFC-0099 forbids dual memory authority; RFC-0092 forbids OpenViking-as-TTS). Without this RFC, “graph-as-memory” dies as a slide.

## Decision

Implement an **Obsidian-compatible linked brain** as a Jarvis-owned **ReferenceStore** that the orchestrator can **read, follow, and act on**. Jarvis remains the orchestrator. Obsidian (the app) is optional; **plain Markdown + wiki-links on disk** are required.

### 1. Canonical ownership

| Layer | Authority |
| --- | --- |
| Structured facts, permissions, provenance indexes | Jarvis DB (`backend/app/memory/`) — RFC-0011 |
| Human-readable linked knowledge (notes, decisions, project pages, manuals) | Owner vault Markdown (this RFC) |
| Optional retrieval sidecar | OpenViking / RAGFlow (RFC-0099) **indexing the same files** — disable sidecar ⇒ vault + native memory still work |

Do **not** replace the FastAPI orchestrator, task state, or DB with Obsidian. Do **not** dump raw tool traces or chain-of-thought into the vault. Do **not** inject the whole vault into a prompt.

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

- **Vault → Jarvis:** indexed excerpts become retrievable context (docs-first / ContextRepo search). High-impact facts may be proposed as RFC-0011 memory mutations (approval/verification unchanged).
- **Jarvis → vault:** selected durable decisions/procedures/project pages are written as Markdown notes with `jarvis_managed: true` and a pointer back to the memory/task id. Episodic chatter stays in DB/journal (RFC-0028), not the brain.

Router.md is a compact orientation file for local models, not a dump of the vault.

### 5. Pattern source (optional clone)

`Rob-Morris/obsidian-brain` (MIT) is the **pattern** source (router/taxonomy/living vs temporal). Extract conventions; do **not** vendor the runtime as a hard dependency. Optional later MCP adapter for an external Brain process; Jarvis **must** work against the Markdown files with that process down. RFC-0095 Download may clone it into the library; Download ≠ integrate.

**Architect’s initial recommendation:** native ReferenceStore + graph actions (`partial` / extract). Taco can override to `archive_only` on the Brain repo while still requiring vault binding.

**Will not:** vendor Obsidian or Brain; replace ContextRepo/DB; use OpenViking as TTS; merge persona packs; HexStrike; offensive tools; dump full vault into prompts.

## Acceptance criteria

Pipeline below is **spec’d** here; product code is the later named ticket (full intent, not a stub “vault path saved, retrieval always empty”).

- [ ] Specs-only in this PR (no `frontend/src` / backend product edits; no vault/clones committed)
- [ ] Owner can bind a local vault path; Jarvis watches Markdown and incrementally reindexes
- [ ] Wiki-links / backlinks resolve; retrieval returns path + heading + hash; neighborhood is hop-capped
- [ ] Jarvis can create/update managed notes that open in Obsidian and any text editor
- [ ] User vault edits win; conflicts surface; broken-link health exists
- [ ] Sync with RFC-0011 memory is explicit + provenanced; disabling RFC-0099 sidecars leaves vault + native memory working
- [ ] Orchestrator never injects the full vault; raw traces stay out of the vault
- [ ] Light §59 Decision Log line only (via `INTEGRATION_SPECS.md` batch)
- [ ] Implement follow-up: `python3 -m pytest`; if portal touched, `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | new `backend/app/memory/obsidian_vault.py` (or `backend/app/context/obsidian.py`) — bind, watch, index, graph resolve, health; `backend/app/memory/repository.py` / `backend/app/memory/store.py` sync hooks; `backend/app/api/memory.py` + `backend/app/api/context_repo.py` vault search/act endpoints; settings path persistence |
| Frontend (implement PR only) | `frontend/src/pages/Memory.tsx`, `ContextRepo.tsx` — vault picker, health, broken links; Settings knowledge/integrations deep-link; not a full Obsidian clone UI |
| Tests | `tests/test_rfc0107_*.py` — link resolve, incremental index, user-edit wins, sidecar-off still works, no full-vault inject |
| Docs | this RFC; `INTEGRATION_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. Vendoring Obsidian/Brain. RFC-0099 implement. RFC-0092 voice. Persona merge (RFC-0104). HexStrike / RFC-0105. Swarm. Instagram scraper. Committing owner vaults.

## Notes

- Source: Taco high-impact add 2026-09-17 (not in the original reel reserved list). Tip latest was RFC-0106; this number is **0107**.
- Linux cloud can unit-test a temp vault + watch fixtures. Live Obsidian app + large vault is Windows desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
