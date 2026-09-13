# RFC-0085: Universal task fast path

**Status:** accepted
**Queue item:** Every request receives an immediate useful response before durable task orchestration.
**Author:** Taco request via Codex
**Date:** 2026-09-13

## Problem

Jarvis routes ordinary requests through the full autonomous task loop. A weather question can consequently make several model calls, expose irrelevant tools, create a plan, wait for verification, and fail to answer despite a warm local model. The same delay can affect any task before Jarvis has established whether planning is necessary.

## Decision

Add a universal response-first stage before the durable task loop. It emits a concise direct answer when the request is answerable without tools, or an immediate acknowledgement plus a clear activity transition when tools or multi-step work are required. Classification, tool exposure, planning, and verification then run only at the smallest level needed by the request. Preserve the existing task path for explicit files, installs, coding, external actions, and long-running work.

The fast stage does not bypass safety policy, fabricate live facts, or perform side effects. Live factual lookups use dedicated briefings (for example RFC-0084 weather) instead of agent-written scripts.

## Acceptance criteria

- [ ] Every submission is classified into direct reply, direct lookup, or managed task before an agent loop begins.
- [ ] Direct replies use one model call, no tool catalog, no verifier, and return within the configured interactive budget.
- [ ] Direct lookups provide a visible immediate status and invoke only their dedicated lookup path; weather remains conversational under RFC-0084.
- [ ] Managed tasks publish an immediate acknowledgement and only expose tools required by their classified intent.
- [ ] A task record captures routing decision, queue delay, model/tool/verifier timings, and the first useful response latency.
- [ ] Follow-ups are independently rerouted rather than inheriting a previous task's expensive workflow.
- [ ] Unit tests pass (`python -m pytest`); frontend build passes if UI changes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/planning.py`, `backend/app/agent/loop.py`, `backend/app/api/tasks.py`, `backend/app/persona/owner_chat.py`, `backend/app/models.py` |
| Frontend | `frontend/src/chat/*`, task activity components |
| Tests | `tests/test_planning.py`, `tests/test_agent_loop.py`, new routing/latency tests |

## Out of scope

Changing model providers, bypassing approvals, parallel swarm execution, voice-engine changes, or broad task-schema migration.

## Notes

RFC-0083 keeps conversational follow-ups out of the tool loop. RFC-0084 owns weather-specific lookup and Android presentation. Desktop sign-off must measure first useful response separately from total managed-task completion time.
