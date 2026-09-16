# RFC-0099: OpenViking + RAGFlow agent memory / RAG module

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** RFC-0011 context repositories + consolidation. RFC-0020 project knowledge. RFC-0028 off-context journal. RFC-0060 docs-first grounding. RFC-0092 (**OpenViking is not TTS**). `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS.md` §2.7 / SPEC-OPENVIKING-001.

This PR is **specs-only**. Do not commit local clones.

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clones (already downloaded; **do not commit**):

| Repo | Canonical | Local path |
| --- | --- | --- |
| OpenViking | [volcengine/OpenViking](https://github.com/volcengine/OpenViking) | `/workspace/projects/rfc/openviking` |
| RAGFlow | [infiniflow/ragflow](https://github.com/infiniflow/ragflow) | `/workspace/projects/rfc/ragflow` |

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** at `/workspace/projects/rfc/{openviking,ragflow}`. Not vendored. |
| 2. Usefulness review | **Score 4/5.** Primary bucket: `module` (agent memory / RAG). Secondary: `mas_integration`. |
| 3. Integrate decision | **`partial`** — optional ContextBackend / RAG sidecar. Jarvis DB + ContextRepo stay canonical. Taco can override. |
| 4. Implement | Later named ticket. |

## Problem

Jarvis already owns structured memory (`backend/app/memory/`, RFC-0011 ContextRepo, consolidation, provenance). Instagram-jarvis saves name OpenViking (hierarchical context filesystem) and RAGFlow (document RAG engine) as memory/RAG modules. There is no sidecar adapter. Risk: someone wires OpenViking as **TTS** (RFC-0092 explicitly forbids that) or replaces Jarvis memory with a second authority.

## Decision

Add an **optional agent-memory / RAG module** (`partial`).

1. **OpenViking is agent memory / hierarchical context — not TTS, not a voice engine.** Do not propose it for RFC-0092 / speak path / Kokoro / SAPI.
2. **RAGFlow** is the document-ingest + retrieval engine (chunk, parse, cite). Use it for project/docs RAG, not as the orchestrator.
3. **Canonical ownership stays Jarvis:** SQLite/structured facts, ContextRepo Markdown, trajectories, policy. Sidecars may **index, enrich, retrieve, or shadow-test**. Disabling them leaves Jarvis memory functional (`EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS_V2.md`).
4. **License:** OpenViking main project is **AGPLv3**. Do not vendor/copy AGPL implementation into Jarvis. Prefer a separately installed HTTP/MCP/SDK sidecar. RAGFlow similarly: adapter over a local service, not a tree merge.
5. Surface as an optional ContextBackend (`OpenVikingContextBackend` / `RAGFlowRetriever`) behind existing memory/context-repo APIs (`backend/app/api/memory.py`, `backend/app/api/context_repo.py`). Docs-first grounding (RFC-0060) may query the retriever; it must not skip internal docs.

**Architect’s initial recommendation:** `partial` sidecar. Taco can override to `archive_only` (license caution) or `whole` (not recommended — dual memory authority).

**Will not:** claim OpenViking is TTS; replace ContextRepo; vendor AGPL; merge persona; HexStrike.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (paths above; clones not committed)
- [x] Usefulness review — spec’d (4/5, `module`)
- [x] Integrate decision — spec’d (`partial` sidecar; Taco may override)
- [ ] Implement — later named ticket (not this PR)
- [ ] Optional OpenViking context sidecar + RAGFlow retriever; Jarvis memory remains canonical
- [ ] OpenViking never appears on the TTS/voice path
- [ ] AGPL not vendored into Jarvis git
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0099_*.py` — disable sidecar ⇒ native memory still works)

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/memory/`; `backend/app/api/memory.py`; `backend/app/api/context_repo.py`; new `backend/app/memory/openviking.py` / `ragflow.py` adapters |
| Frontend (implement PR only) | `frontend/src/pages/Memory.tsx`, `ContextRepo.tsx` — sidecar status only |
| Tests | `tests/test_rfc0099_*.py`, existing memory/context-repo tests |
| Docs | this RFC; §59 batch line only |

## Out of scope

Product implementation in this PR. TTS/voice (RFC-0092 / 0075). Replacing Jarvis DB. Vendoring AGPL. Persona merge. Offensive tools (LE-gated under RFC-0095).

## Notes

- Parent RFC-0095 reserved this number. RFC-0092: “OpenViking is agent memory, not TTS.” Repeat that here so implementers cannot “fix voice” with OpenViking.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`.
