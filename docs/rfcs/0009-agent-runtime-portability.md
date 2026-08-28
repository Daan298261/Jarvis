# RFC-0009: Agent runtime portability

**Status:** accepted  
**Queue item:** Persistent agents / runtime independence  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Logical agent identity, memory, learned skills, and policy must not become tied to one model, node, or interface. Otherwise swarm scheduling and model escalation create fragmented copies of the same specialist.

## Decision

Make `AgentProfile` the durable identity boundary. Model/runtime/node are execution leases, not identity. Agent memory, policy, skill references, active goals, and durable task state remain portable and can be executed by different compatible runtimes.

Introduce explicit serialization/versioning for the portable agent state and runtime compatibility checks before dispatch.

## Acceptance criteria

- [ ] Durable Agent ID remains stable across model, node, and endpoint changes.
- [ ] Agent state can be serialized/restored without runtime-specific objects.
- [ ] Runtime leases record executor node/model without mutating logical identity.
- [ ] Migration/resume preserves memory, policy, task state, and provenance.
- [ ] Incompatible runtime/tool requirements produce a scheduler error, not silent degradation.
- [ ] Tests move the same agent between at least two scripted runtime profiles.
- [ ] Audit log preserves executor history.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | Agent Profile/state store, scheduler, runtime abstraction |
| Tests | portability/resume tests |
| Docs | agent identity contract |

## Out of scope

Live process checkpoint migration and GPU-memory migration.

## Notes

Inspiration: Letta stateful Agents SDK. Recommendation: ADAPT.
