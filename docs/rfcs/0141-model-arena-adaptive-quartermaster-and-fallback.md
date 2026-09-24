# RFC-0141: Model Arena and adaptive Quartermaster

**Status:** accepted  
**Date:** 2026-09-24

## Problem

Static model preferences cannot reliably make Anzu excel across coding, research, vision, voice, planning and cheap utility work on heterogeneous local hardware.

## Decision

Extend the existing router into a Model Quartermaster backed by measured capability profiles. Signals include task/persona, context size, tool support, modality, privacy, cost, latency, availability, hardware fit, historical eval quality and recent failures. Strategies: LOCAL_ONLY, LOCAL_FIRST, BEST_RESULT and COST_OPTIMIZED remain owner-facing policy constraints.

Add Arena: run the same sanitized task/eval against selected models, judge with deterministic rubrics where possible and blinded evaluator models where necessary, retain artifacts, and update an exponentially weighted performance profile. Never train routing from owner-sensitive prompt contents; store task-class metrics and anonymized outcomes. Health failures trigger bounded fallback chains.

## Acceptance criteria

- [ ] Capability profile per model/provider includes measured quality, latency, context, modality, tool reliability, cost and hardware fit.
- [ ] Router selection emits inspectable signals/reason and obeys privacy/cost modes.
- [ ] Arena supports local and cloud models with blinded ordering and reproducible fixtures.
- [ ] Fallback on provider/model failure is bounded and preserves task state.
- [ ] Learning cannot override explicit owner model choice or LOCAL_ONLY.
- [ ] Cold-start defaults work before historical measurements exist.
- [ ] UI shows selection reason and recent benchmark evidence.

## Likely files

Existing model router/profile manager, `backend/app/evals/arena/`, telemetry DB, Models UI, tests.
