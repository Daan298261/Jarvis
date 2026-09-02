# RFC-0028: Off-context agent journal

**Status:** accepted  
**Author:** competitor-watch automation  
**Date:** 2026-09-02

## Problem

Long-running Jarvis agents need somewhere to record provisional thoughts, observations, hypotheses, summaries, and work-in-progress notes without polluting authoritative memory or repeatedly consuming live model context. Today Jarvis has structured memory, context repositories, trajectories, and consolidation, but no explicit low-cost scratch/journal tier with promotion rules. Writing every transient thought into durable memory risks duplication, stale beliefs, context bloat, and accidental behavior changes.

## Decision

Add an append-oriented `AgentJournal` as a distinct, non-authoritative memory surface. Journal entries are stored outside the agent's normal active prompt and are retrieved only on explicit query, task resume, or consolidation. Entries may contain observations, unresolved questions, hypotheses, temporary plans, reflections, and summaries, but they MUST NOT become policy, durable facts, skills, or active adaptations merely because an agent wrote them.

Each entry should record at minimum: `journal_entry_id`, `agent_id`, `scope`, `created_at`, `entry_type`, `content`, `source_execution_id`, `source_refs`, optional `expires_at`, and `promotion_state` (`UNREVIEWED`, `CANDIDATE`, `PROMOTED`, `DISMISSED`).

Journal writes should be cheap and append-oriented. Retrieval should support time range, task/project scope, semantic/full-text search, and source execution. The normal model context receives only selected journal excerpts, never the whole journal.

A consolidation workflow may inspect journal entries and propose promotion into the existing structured memory/context repository pipeline. Promotion must preserve provenance and follow the existing confidence, verification, and policy rules. Deleting or compacting journal entries must not delete already-promoted durable memories.

## Acceptance criteria

- [ ] Jarvis exposes an `AgentJournal` persistence API independent from authoritative memory and Agent Context Repository storage.
- [ ] Agents can append journal entries without causing automatic prompt injection into subsequent turns.
- [ ] Journal entries support agent/project/workflow/task scope, timestamps, provenance, entry type, optional expiry, and promotion state.
- [ ] Retrieval supports full-text or semantic search plus filtering by scope/time/source execution.
- [ ] Task resume may request a bounded set of relevant journal entries instead of replaying an entire trajectory.
- [ ] Journal content is explicitly treated as untrusted/non-authoritative until promoted.
- [ ] Consolidation can convert selected entries into existing memory candidates while preserving source links and applying existing confidence rules.
- [ ] Duplicate/promoted entries are not repeatedly promoted on later consolidation runs.
- [ ] Retention/compaction can prune old journal entries by policy without altering promoted durable records.
- [ ] UI/API distinguishes Journal from Memory so users can inspect and clear scratch history without deleting durable knowledge.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal UI is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/memory/...`, `backend/app/agents/...`, persistence/models for journal storage |
| Consolidation | existing memory-maintenance / context-repository services |
| API | agent/memory routes for append/search/promote/clear |
| Frontend | Memory/Agent detail views if journal inspection is exposed |
| Tests | `tests/test_agent_journal.py`, memory consolidation tests |
| Docs | `docs/rfcs/0028-off-context-agent-journal.md` |

## Out of scope

Changing the authoritative memory schema wholesale; replacing trajectories; hidden chain-of-thought storage; allowing journal entries to grant permissions or modify policy; cross-agent shared memory semantics beyond existing scope rules.

## Notes

Competitor/source: SanctumOS, "Athena Diary: free writing without burning core" (published 2026-08-10): https://sanctumos.org/ and https://sanctumos.org/blog.php  
Discovery date: 2026-09-02  
Recommendation: **ADAPT STRONGLY**. Jarvis should adapt the architectural separation between free-form agent journaling and core memory, but integrate it with Jarvis's existing provenance, scoped memory, confidence lifecycle, context repositories, and consolidation pipeline rather than copying SanctumOS's implementation or terminology.