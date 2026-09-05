# RFC-0010: Cross-harness trajectory ingestion

**Status:** implemented  
**Queue item:** Trajectories / learning from external agents  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Work performed through Cursor, Codex, Claude Code, OpenHands, or other harnesses is currently siloed. Jarvis cannot reliably learn reusable lessons from those sessions.

## Decision

Define `JarvisTrajectoryV1`, a normalized event format for external and native agent runs. Add adapters that convert supported harness logs into normalized trajectories containing harness/model identity, repository/workspace, actions, tool calls, outcomes, failures, recovery, verification, and candidate learned skills.

Imported trajectories are untrusted evidence until validated; they do not directly grant capabilities or modify policy.

## Acceptance criteria

- [x] Publish a versioned normalized trajectory schema.
- [x] Native Jarvis execution can emit the same schema.
- [x] At least one external harness adapter is implemented end-to-end.
- [x] Imported events preserve timestamps/order and source provenance.
- [x] Secrets and credential material are redacted before persistence.
- [x] Outcome/verification fields distinguish attempted work from validated success.
- [x] Memory/skill pipeline can consume normalized trajectories asynchronously.
- [x] Tests cover malformed logs, redaction, ordering, and provenance.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | trajectory schema/store/import adapters |
| Tests | trajectory parser/redaction tests |
| Docs | trajectory format |

## Out of scope

Executing external harnesses themselves; this RFC only normalizes experience.

## Notes

Inspiration: Letta cross-harness trajectory format. Recommendation: ADAPT.

Landed on `cursor/local-qwen-desktop-agent`: backend PR #63 (`412ce01`) — compose with `agent/trajectory.py`; stay off `db/models.py`; portal UI PR #85 (`599a30e`) — list/inspect, Cursor import, native emit; no secrets.
