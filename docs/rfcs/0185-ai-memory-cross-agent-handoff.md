# RFC-0185: Cross-agent AI memory handoff

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md). Living index: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #3).  
**Complements:** [RFC-0099](0099-openviking-ragflow-memory.md), [RFC-0107](0107-obsidian-linked-memory-brain.md), [RFC-0132](0132-supermemory-semantic-recall-sidecar.md).  
**Related (do not rewrite):** RFC-0011 ContextRepo. RFC-0104 Hermes hold. RFC-0183 Obsidian skills. RFC-0184 Ripwire (code map, not memory).

This file is **specs-only**. Do not vendor `akitaonrails/ai-memory`. Obsidian Markdown stays the human canonical vault. Full intent. **No stubs / soft-fail.**

## Problem

Jarvis memory (SQLite / ContextRepo plus the owner vault) does not hand a coding session to a different vendor agent without a re-brief. `akitaonrails/ai-memory` is a local sidecar for that handoff: capture, a git-backed markdown wiki, and a typed claim-once handoff across harnesses. Wiring it as a second brain, or dumping the owner vault into it, would split authority that RFC-0099 and RFC-0107 already forbade.

## Goals

- Optional loopback sidecar for **long-term agent memory and cross-agent handoff** (where the work stopped, what failed, what is still open).
- Jarvis can read a **bounded** handoff/brief into a turn and can write a handoff when the owner asks to continue in another harness.
- Disabling the sidecar leaves ContextRepo, native recall, and the Obsidian vault working.
- Default mode matches upstream’s zero-LLM path. LLM consolidation and embeddings stay opt-in and off until the owner turns them on.

## Non-goals

- Replacing the owner vault. ai-memory’s wiki is **agent** memory. Human canonical notes stay Obsidian Markdown (RFC-0107). OpenViking/RAGFlow (RFC-0099) and Supermemory (RFC-0132) stay their own sidecars.
- Installing upstream hooks that replace the Jarvis plan → act → verify loop, or registering Hermes as a merged butler (RFC-0104).
- Multi-user team hosting, OIDC, or a LAN bind in the first implement ticket. Default is single-owner loopback.
- Vendoring the Rust tree. Invented LE / ATO gates. Treating native Windows as supported when upstream marks it experimental — status must say so (WSL2 is the supported Windows path until upstream says otherwise).

## Contract

| Rule | Requirement |
| --- | --- |
| Source | [akitaonrails/ai-memory](https://github.com/akitaonrails/ai-memory) (MIT). One owner-installed binary. |
| Bind | `127.0.0.1` only unless a later RFC says otherwise. No auth on loopback is acceptable only while nothing off-box can connect. |
| Authority | ContextRepo + Jarvis DB: structured facts. Owner vault: human notes. ai-memory: derived agent wiki and handoffs. Disable sidecar ⇒ the first two still answer. |
| Read | A turn that asks “where did we leave off?” or an explicit continue-in-another-agent ask may inject one bounded brief plus search hits. Not the raw transcript, not the whole wiki. |
| Write | Handoffs and captured observations the owner (or an enabled external harness) asked to store. Do not mirror the entire vault in. Do not delete vault files from this sidecar. |
| Privacy | Upstream sanitization before store stays on. Jarvis must not turn capture off to “simplify,” and must not log credential material into the wiki. |
| Missing | `studio`-style honesty for memory: status `missing` / `stopped` / `ready` / `error`. `ready` only after a live health check. A down server is not an empty successful recall. |
| Fail | Two canonical human stores. A handoff chip with no server. Silent LLM calls in zero-LLM mode. Hooks that swallow Jarvis tool policy. |

External harnesses (Codex, Claude Code, Cursor, others on the upstream matrix) keep their own hook install. Jarvis does not bulk-rewrite those configs in this ticket. Hermes remains `persona_candidate` (RFC-0104); any Hermes↔vault behavior is RFC-0183 skills plus that hold.

## Acceptance

- [x] Spec: optional sidecar, vault stays canonical, loopback, truthful health
- [ ] Implement: health probe; bounded brief on an explicit handoff ask; ContextRepo still answers when the sidecar is stopped
- [ ] Implement: zero-LLM default; opt-in flag required before any consolidation/embedding call
- [ ] Implement: no vault-wide mirror; writes are handoff/observation records with provenance
- [ ] Tests: stopped sidecar does not report a successful empty handoff (`tests/test_rfc0185_*.py`)
- [ ] No vendored tree in the specs PR

## Local clone

Not in git.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/rfc/ai-memory` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\rfc\ai-memory` |

Upstream: https://github.com/akitaonrails/ai-memory

## Lane

**D1** (sidecar supervisor, brief injection, tests). No portal memory redesign in this ticket.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/memory/` sidecar client; settings flag; supervisor |
| Tests | `tests/test_rfc0185_*.py` |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only |

## Out of scope

RFC-0107 embed residual. RFC-0183 skill text. RFC-0184 code map. Replacing RFC-0099 or RFC-0132. Persona merge.
