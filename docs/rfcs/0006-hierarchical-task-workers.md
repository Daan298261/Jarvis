# RFC-0006: Hierarchical short-lived task workers

**Status:** accepted  
**Queue item:** Multi-agent delegation  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

A persistent specialist should be able to parallelize bounded work without creating many permanent Agent Profiles or giving every temporary worker broad authority.

## Decision

Allow eligible senior/logical agents to spawn short-lived child workers for bounded subtasks. Children inherit only explicitly delegated context, tools, budget, deadline, privacy class, and autonomy ceilings. Parent agents remain accountable for aggregation and verification.

## Acceptance criteria

- [ ] Parent can spawn child workers through a typed delegation API.
- [ ] Child authority is always equal to or lower than the parent and platform caps.
- [ ] Delegation includes task, context subset, tool allowlist, budget, deadline, and expected artifact/result schema.
- [ ] Parent receives structured child status/result/failure events.
- [ ] Child workers automatically expire and release resources.
- [ ] Delegation graph is visible in the UI and audit log.
- [ ] Configurable maximum depth/fan-out prevents runaway spawning.
- [ ] Tests cover authority inheritance, expiry, and depth/fan-out limits.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | orchestrator/delegation/scheduler |
| Frontend | agent task tree / execution trace |
| Tests | delegation policy tests |

## Out of scope

Permanent organization hierarchy and marketplace-distributed agent teams.

## Notes

Inspiration: Zoey companion-to-bot hierarchy and modern multi-agent orchestration patterns. Recommendation: ADAPT.
