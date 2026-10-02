# RFC-0085: Universal task fast path

**Status:** implemented
**Implemented:** #479 @ `f2c150b127d76260e0d030a44c44948d24f298ea` on `development` (squash; pre-squash head `e0612996148e63c747de9105523d7b737e56b012`, D1 peer APPROVE). Real hard bypass for warm-model terminal `final_basic` / `ask_clarification` on `direct_reply`, and lean `direct_lookup` (briefing + one `chat_stream`): skip `prepare_answer_route`, progress watchdog, two-lane worker, tool catalog, and background verify. Misses fail closed (`silent_skip` on empty/unsafe terminal fronts so the worker still answers). `backend/app/agent/task_fastpath.py`; diagnostics `task_fastpath` hit/miss; `tests/test_rfc0085_fastpath_hard_bypass.py`. Original response-first stage #235 (`954e01f`).
**Residuals (do not claim done):** configured interactive budget for the whole direct reply (front `timeout_ms` is not that budget); full task-record timing (no queue-delay or verifier-timing columns); direct-lookup weather briefing is still awaited before the front acknowledgement; Desktop first-useful-response soak (cloud cannot sign).
**Queue item:** Every request receives an immediate useful response before durable task orchestration.
**Author:** Taco request via Codex
**Date:** 2026-09-13

## Problem

Jarvis routes ordinary requests through the full autonomous task loop. A weather question can consequently make several model calls, expose irrelevant tools, create a plan, wait for verification, and fail to answer despite a warm local model. The same delay can affect any task before Jarvis has established whether planning is necessary.

## Decision

Add a universal response-first stage before the durable task loop. It emits a concise direct answer when the request is answerable without tools, or an immediate acknowledgement plus a clear activity transition when tools or multi-step work are required. Classification, tool exposure, planning, and verification then run only at the smallest level needed by the request. Preserve the existing task path for explicit files, installs, coding, external actions, and long-running work.

The fast stage does not bypass safety policy, fabricate live facts, or perform side effects. Live factual lookups use dedicated briefings (for example RFC-0084 weather) instead of agent-written scripts.

## Acceptance criteria

- [x] Every submission is classified into direct reply, direct lookup, or managed task before an agent loop begins. **#235** `route_request`; **#479** `resolve_route_kind` prefers the durable `response_route` before the heavy path.
- [ ] Direct replies use one model call, no tool catalog, no verifier, and return within the configured interactive budget. **Residual:** #479 hard-bypasses warm-model terminal `final_basic` / `ask_clarification` (one front call; skips tool catalog, `prepare_answer_route`, progress watchdog, background verify). There is no configured interactive budget on tip — front `timeout_ms` is not that budget — so this box stays open. Non-terminal fronts miss and fail closed into the worker path.
- [ ] Direct lookups provide a visible immediate status and invoke only their dedicated lookup path; weather remains conversational under RFC-0084. **Residual:** #479 `admit_lookup_fastpath` + `_run_direct_lookup_fastpath` (briefing + one `chat_stream`; no two-lane / verify / progress). `weather_system_message` is still awaited before the front acknowledgement, so immediate status ahead of the lookup is not proven. Weather remains the only `direct_lookup` and stays conversational (Open-Meteo / RFC-0084).
- [x] Managed tasks publish an immediate acknowledgement and only expose tools required by their classified intent. **#235**; **#479** does not admit `managed_task` onto the hard bypass (fail closed).
- [ ] A task record captures routing decision, queue delay, model/tool/verifier timings, and the first useful response latency. **Residual:** the task row stores `response_route`, `first_response_ms`, `model_ms`, and `tool_ms`. No queue-delay or verifier-timing columns. #479 adds diagnostics `task_fastpath` hit/miss counters, not those fields.
- [x] Follow-ups are independently rerouted rather than inheriting a previous task's expensive workflow. **#235**
- [x] Unit tests pass (`python -m pytest`); frontend build passes if UI changes. **#479** `tests/test_rfc0085_fastpath_hard_bypass.py` (no `frontend/` in that PR).

### Residual notes (unchecked — do not mark implemented)

- Interactive budget: no whole-reply interactive budget is configured or measured on tip. Front `timeout_ms` (default 6000) is a front-lane timeout only.
- Full timing fields: queue delay and verifier timing are not on the task record.
- Direct lookup immediate status: the weather briefing is fetched before `generate_front_reply`, so the owner-visible ack is not proven to precede the lookup.
- Desktop soak: first useful response measured separately from total managed-task completion time, on Windows with a real model. Cloud VMs cannot sign this off. No desktop checkbox existed on this RFC; it stays a residual note, not a new acceptance box.

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

Tip audit 2026-09-23 on `development` `d56e2c5` (historical): #388 (`5377938`) only adds an automation-breaker terminal hook; #390 is the RFC-0071 ledger tick. Original response-first stage is #235 (`954e01f`): `route_request` before the agent runner.

Ledger 2026-09-30 after **#479** @ `f2c150b127d76260e0d030a44c44948d24f298ea` (pre-squash `e0612996148e63c747de9105523d7b737e56b012`, D1 peer APPROVE). The 2026-09-23 line that warm-model direct replies still pay a worker plus RFC-0128 background verify is **superseded for terminal fronts**: `admit_fastpath` completes `direct_reply` + safe `final_basic` / `ask_clarification` without `prepare_answer_route`, watchdog, two-lane worker, or `schedule_background_verification`; `should_skip_background_verify` is true for `direct_reply` and `direct_lookup`; misses fail closed. Still open: interactive budget, queue-delay / verifier-timing columns, weather briefing awaited before the front acknowledgement, Desktop first-useful-response soak. Non-terminal fronts (`ack_continue` / `handoff_notice`) still miss into the normal path. No new §58 checkbox.
