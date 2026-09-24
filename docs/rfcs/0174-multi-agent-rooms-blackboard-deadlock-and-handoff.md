# RFC-0174: Multi-agent rooms, blackboard, handoff and deadlock control

**Status:** implemented
**Implemented:** #413 @ `13740066e6409bb3da384026e349c6f65c4fa6a8` (`backend/app/agents/rooms/`).
**Portal:** #417 @ `2cb6c0b2feb56374c2e55007fd8ff5932837592a` (`frontend/src/pages/AgentRooms.tsx`, `backend/app/api/agent_rooms.py`).
**Residuals:** live multi-model room Desktop soak. The portal UI residual is closed by #417.
**Renumbered on development:** was incorrectly `RFC-0140` on main @ `ac18fb32` (collided with companion on-device voice RFC-0140). Canonical on development is **RFC-0174**.  
**Date:** 2026-09-24

## Problem

Anzu can delegate work, but feature parity requires inspectable collaboration among specialists rather than opaque sequential prompting or dumping all histories into every context.

## Decision

Add Agent Rooms: an owner-visible collaboration session with Anzu as supervisor and named specialists as participants. Agents communicate through typed messages: REQUEST, RESULT, QUESTION, CHALLENGE, HANDOFF, BLOCKED and FINAL. A bounded shared Blackboard stores task facts, artifacts, decisions and citations; private persona history remains separate. @mentions explicitly target another specialist.

The supervisor owns task decomposition, concurrency budget, merge/synthesis and termination. Detect repeated message cycles, mutual waits, duplicate work and stalled dependencies. Resolve with deterministic deadlock rules, then supervisor intervention, then owner escalation. Parallelism respects CPU/GPU/VRAM/provider budgets and existing cost/privacy modes.

UI shows room participants, active model, task graph, messages, artifacts and why each handoff occurred. Hidden chain-of-thought is never exposed; only concise rationale/decision metadata.

## Acceptance criteria

- [x] Typed inter-agent protocol and bounded Blackboard exist.
- [x] Parallel delegation and explicit @mention/handoff work.
- [x] Persona histories stay isolated; Blackboard shares only approved task state.
- [x] Deadlock/loop/stall detection terminates pathological collaboration.
- [x] Resource governor caps parallel local/cloud agents.
- [x] Supervisor synthesis cites contributing artifacts/agents.
- [x] Full collaboration is replayable from audit events without hidden reasoning.

## Likely files

`backend/app/agents/rooms/`, orchestrator/router, resource governor, portal websocket/events, `frontend/src/`, tests.

## Notes

Portal UI residual closed 2026-09-24 by #417 @ `2cb6c0b2feb56374c2e55007fd8ff5932837592a`. Owner page is `/rooms` and `/rooms/:roomId`. HTTP routes under `/api/agent-rooms` list, create, read messages, blackboard, and audit replay, and they hand off, synthesize, and terminate. The landed portal loads over REST. It does not add a websocket push, and websocket push is not an open residual. Remaining residual: a live multi-model room on Desktop (cloud VMs have no GPU).
