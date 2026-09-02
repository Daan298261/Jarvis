# RFC-0026: Execution phase and verifier observability

**Status:** accepted  
**Queue item:** Autonomous Operator / command-center UX  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-31

## Problem

Long-running autonomous tasks are hard to supervise when the UI exposes only generic running/completed states. OpenHands recently added live automation phases and inline critic results, highlighting a useful distinction between task lifecycle, current execution phase, and verification outcome. Jarvis already records rich execution events and verifier results, but does not define a compact user-facing contract for showing what an agent is doing now, why it is waiting, and whether the delivered result was independently verified.

## Decision

Add a normalized `ExecutionPhase` projection over existing execution events, plus a structured `VerificationSummary` shown inline with task progress and final results.

Core phases: `QUEUED`, `PLANNING`, `GATHERING`, `EXECUTING`, `WAITING_EXTERNAL`, `WAITING_APPROVAL`, `VERIFYING`, `RECOVERING`, `FINALIZING`, `COMPLETED`, `FAILED`, `CANCELLED`, and `DEGRADED`.

The phase is an observable projection, not a second workflow engine. Workers emit structured phase transitions/events; the orchestrator determines the effective task phase and records start/end timestamps, active worker/node, blocking reason where applicable, and progress counters when deterministic totals exist. Do not fabricate percentage-complete estimates from LLM guesses.

`VerificationSummary` records verifier identity/type, checks performed, pass/fail/degraded result, evidence references, unresolved warnings, and whether the final user-facing answer changed because of verification. The UI renders this alongside the result and allows expansion into underlying observable evidence without exposing hidden chain-of-thought.

## Implementation recommendation

Make this the standard status contract for every long-running Jarvis execution surface rather than a special view used only by coding agents. Home task rows, task detail, Away Mode, automations, remote channels, and future guest/customer views should all consume the same backend projection.

Keep lifecycle and phase separate. A GoalRun may remain `RUNNING` while its current phase changes from `PLANNING` to `EXECUTING` to `WAITING_APPROVAL` and back to `EXECUTING`. Terminal lifecycle state remains authoritative; phase explains what is happening now.

Use observable events to derive phase wherever possible. Workers may emit explicit phase hints, but the projection service must be able to infer obvious phases from structured events such as approval creation, verifier start, external-job wait, recovery attempt, and terminal completion. Conflicting or stale worker hints must not overwrite stronger orchestrator state.

Every active task should expose a concise `current_activity` string generated from structured state where possible, for example `Running test suite`, `Waiting for approval: publish campaign`, or `Verifying 3 changed files`. This is presentation text, not hidden reasoning. The UI should prefer the concrete operation/tool/work unit over generic text such as `Thinking...`.

Do not show synthetic LLM completion percentages. Numeric progress is allowed only when Jarvis has a known denominator or a provider supplies trustworthy progress. Good examples include `7 / 12 files`, `3 / 5 subtasks`, or a remote render service's reported 62%. When total work is unknown, show phase, elapsed time, current activity, and completed work units instead.

Track phase start time and accumulated duration so stuck work is visible. Define configurable stale-phase detection for states that should normally advance. A stale phase is an observability signal, not automatic proof of failure; it may create a warning, trigger health inspection, or feed recovery policy.

Parallel work requires aggregation. The parent task should display the dominant phase plus compact child-worker counts, e.g. `Executing — 3 workers active, 1 waiting`. Task detail can expand each child execution with its own phase. One blocked child should not make the entire parent appear blocked if useful parallel work is still running.

Verification must be first-class rather than a decorative badge. Final results should distinguish execution success from verification status. `COMPLETED + NOT_VERIFIED` is valid when verification was not required, but it must not render identically to `COMPLETED + VERIFIED`. A failed required verifier changes the effective result to failed or degraded according to policy.

`VerificationSummary` should support deterministic checks, independent agent critics, human review, external CI/test systems, and domain-specific verifiers using a common structure. Each check records type, target, result, evidence reference, severity, and optional remediation. The aggregate verifier status is derived from those checks and policy rather than chosen by the model.

For software work, evidence may include tests/build/lint results and changed-file inspection. For research, it may include citation/source checks. For publishing or marketing, it may include schema/preview/policy checks. Domain Packs may add verifier types without changing the core execution-phase model.

The UI should default to compactness: one phase indicator, one concrete activity line, optional elapsed/progress, and a verification badge. Rich event history, child workers, evidence, retries, and warnings belong in expandable task detail. This follows Jarvis's clean command-center direction rather than turning the home screen into an operations HUD.

## Acceptance criteria

- [ ] Define the canonical execution phase enum and legal transition rules.
- [ ] Existing task/worker/tool events can be projected into one effective current phase without introducing a duplicate scheduler.
- [ ] Goal/task lifecycle state is stored separately from current `ExecutionPhase`; phase transitions do not accidentally terminate or restart the GoalRun.
- [ ] Every phase transition records timestamp, execution/task ID, source worker/service, and optional blocking reason.
- [ ] Every active execution exposes a concise observable `current_activity` field that does not contain hidden chain-of-thought.
- [ ] `WAITING_APPROVAL` links directly to the relevant Decision Inbox item; approving/rejecting causes a subsequent observable transition.
- [ ] `WAITING_EXTERNAL` distinguishes rate limits, remote job completion, unavailable dependency, and other externally blocked states where known.
- [ ] Progress percentages are shown only when based on deterministic work units or trustworthy provider-reported progress; otherwise UI shows phase/activity without invented percentages.
- [ ] Known-unit work supports explicit `completed_units`, `total_units`, and human-readable unit type.
- [ ] Track current-phase start time and accumulated phase durations; expose a configurable stale-phase warning without automatically declaring failure.
- [ ] Parent executions aggregate parallel children without hiding continued useful work behind one blocked child; detailed views expose each child phase.
- [ ] Define structured `VerificationSummary` with verifier, checks, result, evidence refs, warnings, and timestamp.
- [ ] Individual verification checks include type/target/result/severity/evidence and optional remediation, allowing deterministic, agent, human, external-CI, and domain verifiers under one contract.
- [ ] Final task views show verification state as `VERIFIED`, `VERIFICATION_FAILED`, `PARTIALLY_VERIFIED`, or `NOT_VERIFIED` using objective recorded evidence.
- [ ] Execution success and verification state are visually and semantically distinct; an unverified success is never presented as equivalent to a verified success.
- [ ] Failed required verification prevents a task from being presented as fully successful unless policy explicitly permits a degraded result.
- [ ] UI shows current phase compactly on home/task rows and richer phase history in task detail.
- [ ] Home/task-row presentation remains compact: phase, concrete activity, optional deterministic progress/elapsed time, and verification status; detailed telemetry is expandable rather than always visible.
- [ ] Phase history and verifier evidence are included in audit/export APIs.
- [ ] The same phase/verification projection can be consumed by desktop UI, Away Mode/automations, and RFC-0025 channel notifications without transport-specific lifecycle logic.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | execution event projection, task status service, verifier result schema/API |
| Frontend | task rows, task detail/activity transcript, verification panel |
| Tests | transition rules, approval waits, degraded/verification outcomes |
| Docs | execution status and verifier semantics |

## Out of scope

Changing verifier algorithms; adding speculative LLM-generated completion percentages; workflow scheduling changes; replacing the existing execution event model.

## Notes

Source: https://www.openhands.dev/ and OpenHands 1.16.0 release notes (2026-08-27), including live automation phase display; related May 2026 product update exposed critic results inline.  
Discovery date: 2026-08-31  
Recommendation: ADAPT.  
Jarvis is adapting the observability pattern, not the OpenHands UI implementation. The design intentionally reuses Jarvis execution events and verification rather than creating parallel task state.

Recommended UX target: instead of a generic `Running...`, show a truthful sequence such as `Planning -> Gathering -> Executing -> Waiting for approval -> Verifying -> Completed`, with concrete activity and evidence. A final result may render `VERIFIED — tests passed, output inspected, 0 unresolved warnings`; if those facts were not recorded, Jarvis must not claim them.