# RFC-0071: Automation failure circuit breaker

**Status:** accepted  
**Queue item:** P3/P4 — automation reliability / resilient execution  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-11

## Problem

Jarvis already defines bounded retries, durable goals, idempotent event delivery, and portable automation packages, but a recurring automation that repeatedly fails can still wake indefinitely across schedule/event deliveries and waste compute, API quota, money, or operator attention. OpenHands Automation 1.11.0 added automatic disabling for consecutively failing automations, providing a concrete production pattern for preventing a broken unattended workflow from repeatedly consuming resources.

## Decision

Add a persistent failure circuit breaker to scheduled and event-triggered Jarvis automations. Each automation tracks consecutive terminal run failures independently of per-run retry attempts. After a configurable policy threshold, Jarvis transitions the automation from `ACTIVE` to `DEGRADED` and then `DISABLED_BY_FAILURE`, suppresses future automatic triggers, and surfaces the exact reason and recent failure evidence to the operator.

A successful verified run resets the consecutive-failure counter. A manually cancelled run, skipped condition, approval wait, node migration, or duplicate/idempotently suppressed trigger does not count as a failure unless its final normalized outcome is explicitly `FAILURE`. Per-run retry/backoff remains governed by existing execution policy; this RFC adds a circuit breaker across runs rather than another retry system.

Re-enabling requires an explicit owner/admin action or a separately authorized repair workflow. Re-enable resets or acknowledges the breaker state atomically and is audited. An acting automation/agent cannot silently re-enable itself after tripping the breaker.

## Acceptance criteria

- [ ] Persist per-automation `consecutive_failure_count`, `failure_threshold`, `last_failure_at`, `last_failure_summary`, `breaker_state`, and `disabled_at` without storing hidden chain-of-thought.
- [ ] Support at least `ACTIVE`, `DEGRADED`, and `DISABLED_BY_FAILURE` breaker states; state transitions are deterministic and restart-safe.
- [ ] Only terminal normalized `FAILURE` outcomes increment the cross-run counter; cancellation, skipped/no-op conditions, approval waits, duplicate suppression, and successful/degraded verified outcomes do not incorrectly trip the breaker.
- [ ] A verified successful run resets the consecutive-failure counter to zero.
- [ ] Crossing the configured threshold atomically disables future schedule/event wakeups before another run can be admitted, including under concurrent trigger delivery.
- [ ] Per-run retries/backoff are exhausted or resolved before the automation run contributes one terminal result to the consecutive-failure counter.
- [ ] `DISABLED_BY_FAILURE` automations consume no model/worker compute from subsequent automatic triggers; suppressed triggers may record compact audit events only.
- [ ] UI/API exposes breaker state, threshold, current count, last failure time/summary, recent failed run links, and an explicit `Re-enable` action.
- [ ] Re-enable is owner/admin-authorized, audited, idempotent, and cannot be performed by the affected automation through its own normal tool authority.
- [ ] Audit history records breaker trip, suppressed triggers, threshold/policy used, re-enable actor, and reset/acknowledgement.
- [ ] Tests cover repeated failures across process restarts, success resetting the counter, concurrent triggers at the threshold boundary, retry-vs-run counting, non-failure outcomes, unauthorized self-reenable, and explicit operator recovery.
- [ ] Existing `EventSubscription`/`GoalRun` cancellation and AutomationPackage semantics remain authoritative; no duplicate scheduler or retry engine is introduced.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

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