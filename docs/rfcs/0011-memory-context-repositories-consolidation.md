# RFC-0011: Versioned context repositories and idle-time memory consolidation

**Status:** accepted  
**Queue item:** Memory architecture / background learning  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Long-lived agents accumulate noisy episodic memory. Simply increasing context size does not provide durable organization, provenance, deduplication, or safe background learning.

## Decision

Keep the database as the authoritative structured memory/provenance layer, and add a versioned Agent Context Repository for curated human-readable context such as identity, projects, procedures, lessons, priorities, and skills.

Add a low-priority Memory Maintenance workflow that consumes recent verified trajectories during idle compute, extracts candidate lessons, deduplicates/reorganizes context, and records every proposed mutation. High-impact facts or policy changes require approval or stronger verification.

## Acceptance criteria

- [ ] Context repository structure is versioned and linked to Agent IDs.
- [ ] DB remains authoritative for structured facts, permissions, provenance, and indexes.
- [ ] Consolidation runs only on eligible verified trajectory data.
- [ ] Every memory mutation has source provenance and reversible history.
- [ ] Conflicting facts are retained/flagged rather than silently overwritten.
- [ ] Scheduler can prefer idle/junior nodes for consolidation.
- [ ] User can inspect, diff, revert, pin, and delete curated memory.
- [ ] Tests cover deduplication, conflicting evidence, revert, and scheduling priority.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | memory store, context repo service, background scheduler |
| Frontend | memory history/diff UI |
| Tests | consolidation/provenance tests |
| Docs | memory architecture |

## Out of scope

Replacing Jarvis databases with Git or allowing autonomous policy edits.

## Notes

Inspiration: Letta Context Repositories and sleep-time/defragmentation concepts. Recommendation: ADAPT STRONGLY.
