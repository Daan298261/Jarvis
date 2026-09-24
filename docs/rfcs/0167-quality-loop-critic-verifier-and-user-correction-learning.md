# RFC-0167: Quality Loop — critic, verifier and correction learning

**Status:** accepted  
**Date:** 2026-09-24

## Problem
More autonomy must improve answer/task quality without multiplying model calls indiscriminately.

## Decision
Add task-class quality policies. Cheap/low-risk turns answer directly. Selected research, coding, planning and consequential workflows invoke bounded verifier/critic passes with independent evidence/tools where useful. Material owner corrections are stored as explicit correction records and can update eval fixtures/routing preferences; they never fine-tune or rewrite prompts automatically. Track whether verification actually improved outcomes to disable wasteful loops.

## Acceptance criteria
- [ ] Verification policy is risk/task/quality driven, not universal.
- [ ] Verifier receives enough independent context to catch errors without hidden reasoning exchange.
- [ ] Corrections retain before/after/provenance and owner scope.
- [ ] Eval harness measures quality gain versus latency/cost.
- [ ] Repeated unhelpful verifier paths are surfaced for tuning.

## Likely files
Orchestrator, verifier, evals, Memory Fabric corrections, Control Room/tests.
