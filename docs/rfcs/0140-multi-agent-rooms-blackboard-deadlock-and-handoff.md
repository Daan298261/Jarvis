# RFC-0140: Multi-agent rooms, blackboard, handoff and deadlock control

**Status:** accepted  
**Date:** 2026-09-24

## Problem

Anzu can delegate work, but feature parity requires inspectable collaboration among specialists rather than opaque sequential prompting or dumping all histories into every context.

## Decision

Add Agent Rooms: an owner-visible collaboration session with Anzu as supervisor and named specialists as participants. Agents communicate through typed messages: REQUEST, RESULT, QUESTION, CHALLENGE, HANDOFF, BLOCKED and FINAL. A bounded shared Blackboard stores task facts, artifacts, decisions and citations; private persona history remains separate. @mentions explicitly target another specialist.

The supervisor owns task decomposition, concurrency budget, merge/synthesis and termination. Detect repeated message cycles, mutual waits, duplicate work and stalled dependencies. Resolve with deterministic deadlock rules, then supervisor intervention, then owner escalation. Parallelism respects CPU/GPU/VRAM/provider budgets and existing cost/privacy modes.

UI shows room participants, active model, task graph, messages, artifacts and why each handoff occurred. Hidden chain-of-thought is never exposed; only concise rationale/decision metadata.

## Acceptance criteria

- [ ] Typed inter-agent protocol and bounded Blackboard exist.
- [ ] Parallel delegation and explicit @mention/handoff work.
- [ ] Persona histories stay isolated; Blackboard shares only approved task state.
- [ ] Deadlock/loop/stall detection terminates pathological collaboration.
- [ ] Resource governor caps parallel local/cloud agents.
- [ ] Supervisor synthesis cites contributing artifacts/agents.
- [ ] Full collaboration is replayable from audit events without hidden reasoning.

## Likely files

`backend/app/agents/rooms/`, orchestrator/router, resource governor, portal websocket/events, `frontend/src/`, tests.
