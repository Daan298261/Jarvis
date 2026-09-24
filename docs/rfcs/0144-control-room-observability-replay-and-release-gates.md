# RFC-0144: Control Room, replay harness and release gates

**Status:** accepted  
**Date:** 2026-09-24

## Problem

A system with autonomous goals, specialists and plugins cannot exceed peers reliably without first-class observability and regression control.

## Decision

Create Control Room as the unified operational surface for live turns, routes, agent rooms, goals, workflows, tools, approvals, model selections, resource use and failures. Standardize event envelopes with correlation/trace/span IDs and redacted structured payloads. Build replay from recorded sanitized inputs and deterministic fake providers so regressions can be reproduced without exposing secrets or chain-of-thought.

Add release gates tied to RFC-0137 capability tests: security, migrations, clean install/update/rollback, core offline path, routing, memory, tools and UI smoke tests. A release cannot claim a capability whose required gate fails.

## Acceptance criteria

- [ ] One trace links user request → router → model/persona → tools/subagents → artifacts → final result.
- [ ] Secrets and hidden reasoning never enter telemetry/replay.
- [ ] Replay reproduces state transitions with fake/deterministic providers.
- [ ] Control Room filters by goal/persona/model/tool/node and shows resource/cost metrics.
- [ ] Release gate produces machine-readable pass/fail evidence and blocks configured release cuts.
- [ ] Audit ledger integrity verification is exposed in Control Room.

## Likely files

Events/audit layer, `backend/app/observability/`, replay/evals, release scripts, Control Room UI, tests.
