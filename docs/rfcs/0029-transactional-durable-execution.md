# RFC-0029: Transactional durable execution

**Status:** accepted  
**Queue item:** P4 — resilience / durable autonomous execution  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-04

## Problem

Jarvis already has durable GoalRuns, event subscriptions, checkpoints, retries, execution events, and cancellation semantics, but it does not yet define a hard execution guarantee for process crashes, host restarts, or worker death between model/tool calls. Toren's September 2026 durable-runtime design demonstrates a useful production invariant: every completed model/tool step is committed before the next step advances, so a killed worker can resume without paying for completed model calls again or replaying completed external effects. Long-running Jarvis goals need the same class of crash consistency without replacing Jarvis's existing workflow engine.

## Decision

Add a transactional durable-step layer underneath GoalRun/workflow execution.

Represent each externally meaningful unit as a persistent `ExecutionStep` with stable `run_id`, `step_id`, `attempt_id`, input hash, operation type, effect class, idempotency key where applicable, status, result/evidence reference, cost, timestamps, and predecessor dependencies.

Before advancing to a dependent step, Jarvis must durably record the completed step result and state transition. Recovery reconstructs runnable state from persisted steps/events rather than from in-process memory. A completed deterministic/model step is reused on resume unless its declared replay policy requires recomputation. External-effect tools must declare replay semantics such as `IDEMPOTENT`, `KEYED`, `AT_MOST_ONCE`, or `MANUAL_RECOVERY`; unknown external effects fail closed after ambiguous crashes rather than being blindly replayed.

Use leases/heartbeats for active attempts so another worker can recover abandoned work after lease expiry. Recovery must distinguish `not started`, `started but completion unknown`, and `completed and committed`. Parked waits for approval, timers, rate limits, or external callbacks consume no model/worker loop while waiting and resume from durable state when the wake condition arrives.

Add a crash-injection test matrix that terminates workers at persistence boundaries and verifies that runs either finish correctly or enter a safe explicit recovery state with no duplicate committed effects.

## Acceptance criteria

- [ ] Add persistent `ExecutionStep` and `ExecutionAttempt` records linked to GoalRun/workflow/task IDs with stable step identity, dependencies, operation type, effect class, replay policy, status, cost, and result/evidence references.
- [ ] A dependent step cannot become runnable until predecessor completion/result metadata is durably committed.
- [ ] Recovery after orchestrator/worker process termination reconstructs state from persistent records without requiring the original process memory.
- [ ] Completed model calls and deterministic internal steps are not re-executed on resume unless explicitly marked recomputable/expired.
- [ ] Tool definitions can declare replay semantics: `IDEMPOTENT`, `KEYED`, `AT_MOST_ONCE`, or `MANUAL_RECOVERY`; external-effect tools may not default silently to unrestricted replay.
- [ ] Stable idempotency keys survive retries, worker migration, and process restart.
- [ ] If a crash occurs after an external action may have executed but before completion was committed, Jarvis enters `AMBIGUOUS_EFFECT`/manual reconciliation unless the provider supports a safe keyed lookup or idempotent retry.
- [ ] Active attempts use leases/heartbeats; lease expiry permits another eligible worker to claim recoverable work without creating two authoritative attempts.
- [ ] Approval waits, scheduled waits, rate-limit waits, and callback waits persist a wake condition and release active worker/model resources while parked.
- [ ] Cancellation from RFC-0016 prevents recovery from resurrecting cancelled GoalRuns or spawning new child steps.
- [ ] Resource/cost accounting on resume does not double-count reused completed steps.
- [ ] Execution-phase UI from RFC-0026 can show `RECOVERING` and identify whether work was resumed, reused, retried, or requires ambiguous-effect reconciliation.
- [ ] Add crash-injection tests that terminate the worker before/after every important persistence boundary for representative model calls, internal tools, keyed external effects, approvals, and child work.
- [ ] Crash tests verify no duplicate committed external effect for safely replayable/keyed fixtures and no duplicate model charge in the mocked provider accounting.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | execution/goal-run state service, durable step repository, worker claim/lease logic, recovery coordinator |
| Tools | tool metadata/replay-policy contract, idempotency-key propagation |
| Frontend | recovery/ambiguous-effect state in task detail and Decision Inbox |
| Tests | crash-injection/kill matrix, replay/idempotency, leases, parked waits, accounting |
| Docs | durable execution and recovery semantics |

## Out of scope

Replacing Jarvis's existing workflow/GoalRun abstractions; adopting Toren or Postgres as a mandatory dependency; distributed consensus across multiple active Orchestrators; exactly-once guarantees for third-party systems that do not offer idempotency or status reconciliation; changing tool-specific business logic.

## Notes

Source: https://toren.run/ — September 2026. Toren persists every model/tool call into an event-backed runtime, resumes after process death, reuses completed model calls, parks waiting work without active compute, uses keyed replay semantics for external effects, and validates durability through a kill-at-write-point CI matrix.  
Discovery date: 2026-09-04  
Recommendation: **ADAPT STRONGLY**.  
Jarvis is adapting the crash-consistency invariants and failure-testing discipline, not Toren's implementation choice of making Postgres the entire runtime. The design must integrate with RFC-0016 GoalRun lifecycle, RFC-0026 execution observability, existing Jarvis eventing, policy, and swarm recovery rather than creating a second runtime.
