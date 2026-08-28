# RFC-0010: Cross-harness trajectory ingestion

**Status:** accepted  
**Queue item:** Trajectories / learning from external agents  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Work performed through Cursor, Codex, Claude Code, OpenHands, or other harnesses is currently siloed. Jarvis cannot reliably learn reusable lessons from those sessions.

## Decision

Define `JarvisTrajectoryV1`, a normalized event format for external and native agent runs. Add adapters that convert supported harness logs into normalized trajectories containing harness/model identity, repository/workspace, actions, tool calls, outcomes, failures, recovery, verification, and candidate learned skills.

Imported trajectories are untrusted evidence until validated; they do not directly grant capabilities or modify policy.

## Acceptance criteria

- [ ] Publish a versioned normalized trajectory schema.
- [ ] Native Jarvis execution can emit the same schema.
- [ ] At least one external harness adapter is implemented end-to-end.
- [ ] Imported events preserve timestamps/order and source provenance.
- [ ] Secrets and credential material are redacted before persistence.
- [ ] Outcome/verification fields distinguish attempted work from validated success.
- [ ] Memory/skill pipeline can consume normalized trajectories asynchronously.
- [ ] Tests cover malformed logs, redaction, ordering, and provenance.

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
