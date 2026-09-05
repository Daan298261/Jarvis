# RFC-0011: Versioned context repositories and idle-time memory consolidation

**Status:** implemented  
**Queue item:** Memory architecture / background learning  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Long-lived agents accumulate noisy episodic memory. Simply increasing context size does not provide durable organization, provenance, deduplication, or safe background learning.

## Decision

Keep the database as the authoritative structured memory/provenance layer, and add a versioned Agent Context Repository for curated human-readable context such as identity, projects, procedures, lessons, priorities, and skills.

Add a low-priority Memory Maintenance workflow that consumes recent verified trajectories during idle compute, extracts candidate lessons, deduplicates/reorganizes context, and records every proposed mutation. High-impact facts or policy changes require approval or stronger verification.

## Acceptance criteria

- [x] Context repository structure is versioned and linked to Agent IDs.
- [x] DB remains authoritative for structured facts, permissions, provenance, and indexes.
- [x] Consolidation runs only on eligible verified trajectory data.
- [x] Every memory mutation has source provenance and reversible history.
- [x] Conflicting facts are retained/flagged rather than silently overwritten.
- [x] Scheduler can prefer idle/junior nodes for consolidation.
- [x] User can inspect, diff, revert, pin, and delete curated memory.
- [x] Tests cover deduplication, conflicting evidence, revert, and scheduling priority.

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

Landed on `cursor/local-qwen-desktop-agent`: backend PR #65 (`5c17b5e`) — compose with trajectory store; portal UI PR #84 (`fc111c9`) — inspect/diff/revert/pin/delete; does not replace the existing skills Memory page.
