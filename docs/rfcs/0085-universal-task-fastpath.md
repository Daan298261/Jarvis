# RFC-0085: Universal task fast path

**Status:** implemented
**Queue item:** Every request receives an immediate useful response before durable task orchestration.
**Author:** Taco request via Codex
**Date:** 2026-09-13

## Problem

Jarvis routes ordinary requests through the full autonomous task loop. A weather question can consequently make several model calls, expose irrelevant tools, create a plan, wait for verification, and fail to answer despite a warm local model. The same delay can affect any task before Jarvis has established whether planning is necessary.

## Decision

Add a universal response-first stage before the durable task loop. It emits a concise direct answer when the request is answerable without tools, or an immediate acknowledgement plus a clear activity transition when tools or multi-step work are required. Classification, tool exposure, planning, and verification then run only at the smallest level needed by the request. Preserve the existing task path for explicit files, installs, coding, external actions, and long-running work.

The fast stage does not bypass safety policy, fabricate live facts, or perform side effects. Live factual lookups use dedicated briefings (for example RFC-0084 weather) instead of agent-written scripts.

## Acceptance criteria

- [x] Every submission is classified into direct reply, direct lookup, or managed task before an agent loop begins.
- [ ] Direct replies use one model call, no tool catalog, no verifier, and return within the configured interactive budget.
- [ ] Direct lookups provide a visible immediate status and invoke only their dedicated lookup path; weather remains conversational under RFC-0084.
- [x] Managed tasks publish an immediate acknowledgement and only expose tools required by their classified intent.
- [ ] A task record captures routing decision, queue delay, model/tool/verifier timings, and the first useful response latency.
- [x] Follow-ups are independently rerouted rather than inheriting a previous task's expensive workflow.
- [x] Unit tests pass (`python -m pytest`); frontend build passes if UI changes.

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

Tip audit 2026-09-23 on `development` `d56e2c5`. #388 (`5377938`) only adds an automation-breaker terminal hook in `loop.py` and does not change routing. #390 (`d56e2c5`) is the RFC-0071 ledger tick and does not change routing. Core response-first stage is present: `route_request` in `backend/app/agent/planning.py` classifies before `AgentLoop.create_task` starts the runner (`backend/app/agent/loop.py`); `backend/app/agent/front_responder.py` speaks the first reply. Original land is merged #235 (`954e01f`); D1 tip-audit found no outstanding implement PR. Unchecked: non-trivial direct replies still use a front call plus a worker, and RFC-0128 still schedules a background verifier (front `timeout_ms` is not an interactive budget for the whole reply); weather stays conversational via Open-Meteo but the lookup is awaited before the front acknowledgement, and it is the only `direct_lookup`; the task row stores `response_route`, `first_response_ms`, `model_ms`, and `tool_ms`, not queue delay or verifier timing.
