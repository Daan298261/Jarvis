# RFC-0016: Event subscriptions and durable goal lifecycle

**Status:** accepted  
**Queue item:** Persistent agents / event-driven execution  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-29

## Problem

Jarvis can schedule recurring work and model persistence/proactivity, but it lacks a first-class abstraction for an agent to subscribe to changing external state, wake only when relevant events occur, and own a durable goal until completion. It also needs explicit cancellation semantics so a long-running goal cannot continue consuming resources after the user believes it has stopped.

## Decision

Add `EventSubscription` and `GoalRun` as separate durable runtime objects.

An `EventSubscription` binds an Agent Profile or workflow to an event source such as GitHub PR activity, Slack/thread messages, calendar/schedule events, webhook-compatible integrations, or internal Jarvis events. Matching events enqueue bounded work under the agent's existing policy and budget.

A `GoalRun` represents an objective that may span many task turns. Its lifecycle is explicit: `PENDING`, `RUNNING`, `PAUSED`, `CANCELLING`, `CANCELLED`, `SUCCEEDED`, `FAILED`, `EXPIRED`. `Stop current turn` and `Cancel goal` are distinct operations. Cancellation must revoke future wakeups, prevent new child work, and terminate or drain active work according to policy.

## Acceptance criteria

- [ ] Persist `EventSubscription` with source, filter, owner agent/workflow, enabled state, last cursor/event ID, deduplication key, and policy/budget reference.
- [ ] At least one external event source and one internal Jarvis event source can trigger a subscribed workflow without polling the LLM continuously.
- [ ] Event delivery is idempotent: duplicate deliveries do not create duplicate task executions.
- [ ] Persist `GoalRun` separately from individual turns/tasks and record parent/child work plus cumulative cost/resource usage.
- [ ] `pause` prevents new work but preserves resumable goal state.
- [ ] `cancel` transitions through `CANCELLING` and guarantees no new event wakeups or child tasks can start after cancellation is accepted.
- [ ] UI exposes `Pause turn`, `Pause goal`, and `Cancel goal` as clearly different actions and shows effective state.
- [ ] Hard limits exist for wall-clock lifetime, token/API budget, task count, child-worker count, and retry count; crossing a limit terminates or requests approval according to policy.
- [ ] Goal and subscription activity is auditable with trigger source, event ID, reason for wakeup, costs, and final outcome.
- [ ] Tests cover deduplication, retry, pause/resume, cancellation during active work, cancellation between turns, stale-event replay, and budget exhaustion.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/scheduler/...`, `backend/app/agents/...`, event/subscription and goal-run models/routes |
| Integrations | GitHub/Slack/internal event adapters or generic event-source interface |
| Frontend | persistent-agent/goal activity view and cancel controls |
| Tests | event delivery, lifecycle, cancellation, budget tests |
| Docs | event-driven agent and goal lifecycle documentation |

## Out of scope

Implementing every possible external connector; this RFC defines the event-source contract and proves it with a limited set. Persistence/proactivity policy semantics remain owned by RFC-0014.

## Notes

Source: https://cursor.com/changelog/08-19-26 — Cursor Cloud Agents added Subscriptions that wake on PR, Slack, or scheduled events and persistent goals that keep working until the objective is met. A subsequent public Cursor bug report showed why Jarvis should not copy the lifecycle semantics blindly: `Stop` could pause only the current turn while the durable goal continued starting new work and consuming tokens. Source: https://forum.cursor.com/t/goal-cloud-agent-did-not-stop-continued-for-6-hours-and-burned-tokens/169723

Discovery date: 2026-08-29. Recommendation: **ADAPT STRONGLY**. Jarvis should copy the event-driven wakeup and durable-goal architecture, but implement explicit, enforceable cancellation and resource ceilings from the start.
