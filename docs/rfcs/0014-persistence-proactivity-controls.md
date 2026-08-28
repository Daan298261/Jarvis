# RFC-0014: Separate persistence from proactivity

**Status:** accepted  
**Queue item:** Always-on agents / Away Mode  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

“Always running” and “allowed to invent new work” are different permissions. Combining them in one autonomy switch makes persistent agents unnecessarily risky and hard to reason about.

## Decision

Add two orthogonal policy axes.

Persistence: `ONE_SHOT`, `UNTIL_COMPLETE`, `CONTINUOUS`.

Proactivity: `DISABLED`, `SUGGEST_ONLY`, `CREATE_TASKS`, `EXECUTE_WITHIN_POLICY`.

A continuous agent may therefore monitor forever while only suggesting actions, while another may create or execute bounded work under capability autonomy, budgets, schedules, and approval gates.

## Acceptance criteria

- [ ] Agent Profile stores persistence and proactivity independently.
- [ ] Scheduler honors continuous agents without granting additional capability authority.
- [ ] Proactive task creation records trigger/evidence, rationale, budget, and parent agent.
- [ ] `SUGGEST_ONLY` can never enqueue executable work without approval.
- [ ] `EXECUTE_WITHIN_POLICY` still passes normal per-capability authorization and budget checks.
- [ ] UI clearly shows both axes and effective behavior.
- [ ] Away Mode can override/pause proactivity without destroying persistence configuration.
- [ ] Tests cover every persistence/proactivity combination.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | Agent Profile, scheduler, proactive trigger service |
| Frontend | agent autonomy settings / Away Mode |
| Tests | scheduler/policy matrix tests |
| Docs | autonomy semantics |

## Out of scope

Specific trigger integrations such as email/webhooks; those get separate RFCs.

## Notes

Inspiration: persistent/proactive autonomous coding-agent direction reported for Codex and similar platforms. Recommendation: ADAPT.
