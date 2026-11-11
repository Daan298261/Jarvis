# RFC-0247: Deliver results before optional follow-up work

**Status:** accepted
**Queue item:** Owner-authorized response-time improvements, 2026-11-11
**Author:** Codex desktop session
**Date:** 2026-11-11

## Problem

A measured completion event followed terminal persistence by 16,641 ms. Trajectory memory, usage accounting, skill promotion and speech dispatch currently block completion. Multiple durable transactions and missing Ollama timing accounting also obscure response latency.

## Decision

Persist optional follow-up jobs atomically with task completion. Publish the committed result before processing those jobs in bounded serial delivery and learning lanes, with per-job retries and startup recovery. Keep requested memory writes, verification, resource/security release and coding outcome correctness on the required path. Preserve the selected model and all existing tool policies. Reduce redundant durable transactions only where crash-boundary behavior is preserved. Record provider wall time when provider timings are absent. Index task-event lookups so delivery checks and task polling do not scan the full event history.

## Acceptance criteria

- Blocked memory, accounting, promotion or speech cannot delay the completed event.
- Follow-up jobs survive restart, retry independently and do not duplicate persisted trajectory or usage rows on replay.
- Shutdown cancels the worker cleanly and leaves unfinished work recoverable.
- Explicit memory-write requests still require a successful write before confirmation.
- Durable crash/replay and lease tests continue to pass if transactions change.
- Ollama calls without provider timing metadata produce nonzero model duration.
- Focused tests and available broader pytest checks run; record limitations.

## Likely files

Backend: agent/loop.py, agent/post_response.py, agent/trajectory.py, agent/metrics.py, coding/usage.py, db/models.py, main.py and agent/durable_execution/{runner,repository}.py. Tests: tests/test_post_response.py and existing durable, memory and task-flow tests.

## Out of scope

Model changes, relaxing verification, new connector installation, speculative physical-device timings and unrelated frontend changes. This branch is stacked on the MCP fixes in PR #692; do not overwrite that installed work.
