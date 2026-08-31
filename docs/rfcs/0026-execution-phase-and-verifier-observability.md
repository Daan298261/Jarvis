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

## Acceptance criteria

- [ ] Define the canonical execution phase enum and legal transition rules.
- [ ] Existing task/worker/tool events can be projected into one effective current phase without introducing a duplicate scheduler.
- [ ] Every phase transition records timestamp, execution/task ID, source worker/service, and optional blocking reason.
- [ ] `WAITING_APPROVAL` links directly to the relevant Decision Inbox item; approving/rejecting causes a subsequent observable transition.
- [ ] `WAITING_EXTERNAL` distinguishes rate limits, remote job completion, unavailable dependency, and other externally blocked states where known.
- [ ] Progress percentages are shown only when based on deterministic work units; otherwise UI shows phase/activity without invented percentages.
- [ ] Define structured `VerificationSummary` with verifier, checks, result, evidence refs, warnings, and timestamp.
- [ ] Final task views show verification state as `VERIFIED`, `VERIFICATION_FAILED`, `PARTIALLY_VERIFIED`, or `NOT_VERIFIED` using objective recorded evidence.
- [ ] Failed verification prevents a task from being presented as fully successful unless policy explicitly permits a degraded result.
- [ ] UI shows current phase compactly on home/task rows and richer phase history in task detail.
- [ ] Phase history and verifier evidence are included in audit/export APIs.
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
