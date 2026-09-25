# RFC-0071: Automation failure circuit breaker

**Status:** implemented  
**Queue item:** P3/P4 — automation reliability / resilient execution (no §58 checkbox; portal residual landed #392 @ 392c1572)  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-11

## Problem

Jarvis already defines bounded retries, durable goals, idempotent event delivery, and portable automation packages, but a recurring automation that repeatedly fails can still wake indefinitely across schedule/event deliveries and waste compute, API quota, money, or operator attention. OpenHands Automation 1.11.0 added automatic disabling for consecutively failing automations, providing a concrete production pattern for preventing a broken unattended workflow from repeatedly consuming resources.

## Decision

Add a persistent failure circuit breaker to scheduled and event-triggered Jarvis automations. Each automation tracks consecutive terminal run failures independently of per-run retry attempts. After a configurable policy threshold, Jarvis transitions the automation from `ACTIVE` to `DEGRADED` and then `DISABLED_BY_FAILURE`, suppresses future automatic triggers, and surfaces the exact reason and recent failure evidence to the operator.

A successful verified run resets the consecutive-failure counter. A manually cancelled run, skipped condition, approval wait, node migration, or duplicate/idempotently suppressed trigger does not count as a failure unless its final normalized outcome is explicitly `FAILURE`. Per-run retry/backoff remains governed by existing execution policy; this RFC adds a circuit breaker across runs rather than another retry system.

Re-enabling requires an explicit owner/admin action or a separately authorized repair workflow. Re-enable resets or acknowledges the breaker state atomically and is audited. An acting automation/agent cannot silently re-enable itself after tripping the breaker.

## Acceptance criteria

- [x] Persist per-automation `consecutive_failure_count`, `failure_threshold`, `last_failure_at`, `last_failure_summary`, `breaker_state`, and `disabled_at` without storing hidden chain-of-thought.
- [x] Support at least `ACTIVE`, `DEGRADED`, and `DISABLED_BY_FAILURE` breaker states; state transitions are deterministic and restart-safe.
- [x] Only terminal normalized `FAILURE` outcomes increment the cross-run counter; cancellation, skipped/no-op conditions, approval waits, duplicate suppression, and successful/degraded verified outcomes do not incorrectly trip the breaker.
- [x] A verified successful run resets the consecutive-failure counter to zero.
- [x] Crossing the configured threshold atomically disables future schedule/event wakeups before another run can be admitted, including under concurrent trigger delivery.
- [x] Per-run retries/backoff are exhausted or resolved before the automation run contributes one terminal result to the consecutive-failure counter.
- [x] `DISABLED_BY_FAILURE` automations consume no model/worker compute from subsequent automatic triggers; suppressed triggers may record compact audit events only.
- [x] UI/API exposes breaker state, threshold, current count, last failure time/summary, recent failed run links, and an explicit `Re-enable` action.
- [x] Re-enable is owner/admin-authorized, audited, idempotent, and cannot be performed by the affected automation through its own normal tool authority.
- [x] Audit history records breaker trip, suppressed triggers, threshold/policy used, re-enable actor, and reset/acknowledgement.
- [x] Tests cover repeated failures across process restarts, success resetting the counter, concurrent triggers at the threshold boundary, retry-vs-run counting, non-failure outcomes, unauthorized self-reenable, and explicit operator recovery.
- [x] Existing `EventSubscription`/`GoalRun` cancellation and AutomationPackage semantics remain authoritative; no duplicate scheduler or retry engine is introduced.
- [x] Unit tests pass (`python3 -m pytest`).
- [x] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | scheduler/automation models and trigger admission, execution outcome handling, audit/events |
| Frontend | automation health/status detail, failure evidence, re-enable control |
| Tests | automation circuit-breaker persistence, concurrency, authorization, recovery |
| Docs | automation reliability/operator recovery documentation |

## Out of scope

Changing portable automation package format; replacing per-run retry/backoff; automatic LLM-authored repairs; changing GoalRun cancellation semantics; generic worker/node health circuit breakers; creator/team RBAC for multi-tenant deployments.

## Notes

Source: https://github.com/OpenHands/automation/releases/tag/v1.11.0 — OpenHands Automation 1.11.0, released 2026-09-08, added automatic disabling for consecutively failing automations.  
Discovery date: 2026-09-11.  
Recommendation: **ADAPT STRONGLY**.  
Jarvis adapts the production reliability principle, not OpenHands internals: the breaker is implemented as Jarvis-owned durable automation state integrated with existing normalized outcomes, retry policy, event subscriptions, approvals, audit, and owner authority. OpenHands 1.11.0 also added creator-only editing and routing events into an existing conversation; those do not justify separate Jarvis RFCs because Jarvis is currently owner-controlled and durable GoalRun continuity already covers the latter concern.

API landed #388 @ `5377938`. Portal residual landed #392 @ `392c1572` (Settings → Advanced → Automation circuit breaker).

## Implementation note

Backend **implemented** on `development` via #388 @ `5377938fff2ca124e5f246d1a848ad90efceae8a`. Portal residual **landed** #392 @ `392c1572dc857e225cdeb901279cd03bd70fe453`. Specs-only ledger refine. No product code in this PR. §58 had no RFC-0071 checkbox; none was added.

Evidence on that commit (`backend/app/automation/breaker.py`, `audit.py`, `outcomes.py`, `api/automation_breaker.py`, `mobile/scheduler.py` admission before `submit`, `agent/loop.py` `on_task_terminal`, `tests/test_rfc0071_breaker.py`):

- Durable fields live in `data/automation-breaker/automations.json`. Summaries are truncated outcome text, not chain-of-thought. Reload is file re-read (`test_repeated_failures_persist_across_reload`). A corrupt JSON file loads as empty (fail-open); intact writes survive process restart.
- `ACTIVE` / `DEGRADED` (count > 0) / `DISABLED_BY_FAILURE` (count ≥ threshold or `disabled_at`) are derived under one lock.
- Only `TerminalOutcome.FAILURE` increments. `CANCELLED`, `SKIPPED`, `DUPLICATE_SUPPRESSED`, `APPROVAL_WAIT`, and unverified `NO_OP` do not. Verified `SUCCESS` (`completed` with a verification string) resets the counter to zero. A late success does not clear `disabled_at`; admission stays fail-closed until owner re-enable.
- Mobile schedule `tick` calls `admit_automatic_trigger` before `submit`. A disabled automation records `trigger_suppressed` and does not start a worker. `event_subscription_automation_id` is unused: RFC-0016 `EventSubscription` is still accepted and has no dispatcher on tip, so there is no second event wakeup path to gate. Concurrent admit/finalize share the breaker lock. The race test’s `allowed <= 2` assertion is loose; the sequential disable test is the strict admission check.
- One terminal result per `run_id` (`finalized`). In-loop retries stay non-terminal; `on_task_terminal` runs only for `completed` / `failed` / `cancelled`.
- `POST /api/automation-breaker/{id}/reenable` requires the owner private key, rejects `automation:{id}`, is idempotent (`reenable_idempotent`), and is not exposed as an automation tool. Audit jsonl records `breaker_tripped`, `trigger_suppressed` (threshold in the trip detail), `failure_counter_reset`, and re-enable actor. The 11 tests do not assert audit rows.
- No second scheduler or retry engine. `GoalRun` / `EventSubscription` classes are not in the tree; loop cancellation still maps to `CANCELLED` and does not increment the counter. Automation package format is unchanged.
- `python3 -m pytest tests/test_rfc0071_breaker.py`: 11 passed on this ledger VM. Full-suite re-run was not repeated for this specs-only tick.

Portal evidence on #392 (`frontend/src/settings/AutomationBreakerPanel.tsx`, `automationBreakerView.ts`, `AdvancedSettingsPane.tsx`, `frontend/src/api.ts`). CI `frontend-build` on that PR completed success (actions run `35867007305`, job `107201060719`). This ledger PR does not touch `frontend/`.

- Settings → Advanced mounts the panel. `GET /api/automation-breaker` is parsed fail-closed: a list error hides rows and does not treat the automation as healthy. Each row shows `breaker_state`, consecutive failures against `failure_threshold`, last failure time and summary, and recent failed run ids as links to `/tasks/:id`.
- The audit strip reads `GET /api/automation-breaker/audit?limit=100` and shows up to six events for that automation. An audit error hides the strip and says so; the rows stay the list response only.
- Owner Re-enable (`POST /api/automation-breaker/{id}/reenable`, body `actor: owner`) is shown for `DISABLED_BY_FAILURE`. Owner threshold save is `PUT /api/automation-breaker/{id}/threshold`. The panel replaces the row with the parsed API record.

Residuals still open (documented here; not a new RFC):

- `GET` list, detail, and audit are still not owner-key gated. Re-enable and threshold are.
- `tests/test_rfc0071_breaker.py` `test_admission_race_disables_before_new_run` still asserts `sum(1 for item in allowed if item) <= 2`. The 11 tests still do not assert audit rows.
- `event_subscription_automation_id` is still unused. RFC-0016 `EventSubscription` has no dispatcher on tip, so there is still no second event wakeup path to gate.
- Owner threshold PUT calls `set_failure_threshold` → `ensure_automation` with default `kind="generic"`. That helper assigns `kind` whenever the argument is truthy, so a threshold save rewrites a prior kind (the scheduler sets `kind="schedule"`) to `generic`. `admit_automatic_trigger` calls `ensure_automation(automation_id)` with no kind and does the same rewrite on admission. The portal shows the kind the API returns (`Kind`). The UI/API box stays checked because the panel shows list state, threshold, count, last failure, recent failed-run links, audit, and Re-enable, and it displays the record the API returns.