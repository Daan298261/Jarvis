# RFC-0166: Self-diagnostics, subsystem health and bounded auto-repair

**Status:** accepted  
**Date:** 2026-09-24

## Problem
A complex local assistant needs to explain failures and recover common faults without destructive guesswork.

## Decision
Standardize subsystem health probes for DB, models, GPU/runtime, modules, voice, browser, tools, nodes, channels and storage. Doctor builds a dependency graph and root-cause candidates from evidence. Auto-repair actions are predeclared, reversible/idempotent where possible and risk-rated; anything destructive or ambiguous requires owner approval. Keep before/after diagnostics and rollback data.

## Acceptance criteria
- [ ] Health API distinguishes healthy/degraded/unavailable/misconfigured.
- [ ] Root-cause report links failed dependencies instead of flooding symptoms.
- [ ] Auto-repair only invokes allowlisted repair recipes.
- [ ] Repair records action/evidence/result and rollback availability.
- [ ] Synthetic fault tests cover common install/runtime failures.

## Likely files
Doctor/setup, module/model/node health, Control Room, tests.
