# RFC-0167: Quality Loop — critic, verifier and correction learning

**Status:** accepted  
**Date:** 2026-09-24  
**Updated:** 2026-09-25

## Problem
More autonomy must improve task quality without multiplying model calls indiscriminately. Corrections and execution failures are useful evidence, but production behavior should not change directly from a single trace.

## Decision
Add task-class quality policies. Cheap/low-risk turns answer directly. Selected research, coding, planning and consequential workflows invoke bounded verifier/critic passes with independent evidence/tools where useful.

Material owner corrections, successful recoveries and execution failures become immutable improvement records with task class, before/after outcome, provenance, runtime/model/tool versions and verification result. Candidates use the lifecycle `observed -> normalized -> candidate -> replayed -> verified -> approved -> promoted`, with rejection and rollback states.

Candidates may propose eval fixtures, routing preferences, skill revisions, recovery rules or prompt/config changes. Promotion requires repeatable replay where applicable, regression checks against pinned evaluation fixtures and auditable approval according to Jarvis policy. Every promoted artifact is versioned and independently rollbackable.

## Acceptance criteria
- [ ] Verification policy is risk/task/quality driven, not universal.
- [ ] Verifier receives enough independent context to catch errors without hidden reasoning exchange.
- [ ] Corrections/failures retain before/after/provenance plus model, tool and runtime versions.
- [ ] Improvement records implement explicit lifecycle states and idempotent transitions.
- [ ] Production behavior is not changed directly from an execution trace.
- [ ] Candidate promotion runs replay/evaluation against pinned fixtures and records quality, latency and cost deltas.
- [ ] Failed verification/regression leaves the active version unchanged.
- [ ] Promoted artifacts are versioned, attributable and rollbackable.
- [ ] Repeated unhelpful verifier/recovery paths are surfaced for tuning.
- [ ] Control Room exposes provenance, candidate status, verification evidence, approval and rollback history.

## Likely files
Orchestrator quality policy, verifier/replay harness, evals, Memory Fabric correction records, skill/config version store, Control Room, audit log and tests.

## Out of scope
- Automatic model-weight training from production traces.
- Unreviewed recursive changes to Jarvis behavior.
- Sending private traces to external training services by default.

## Notes
- Source: https://www.perplexity.ai/hub/blog/learning-from-real-world-experience
- Discovery date: 2026-09-25
- Recommendation: ADAPT STRONGLY
- Adaptation: use production corrections/failures as structured evidence for a gated replay/evaluation/promotion pipeline rather than copying an external training stack.
