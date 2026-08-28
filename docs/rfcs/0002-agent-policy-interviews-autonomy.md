# RFC-0002: Agent policy interviews and per-capability autonomy

**Status:** implemented  
**Queue item:** Agent configuration / autonomy controls  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis needs a user-friendly way to configure persistent specialist behavior without forcing users to hand-author system prompts. A single global autonomy switch is too coarse because an agent may safely research autonomously while publishing, spending money, changing credentials, or sending external messages requires stricter authority.

## Decision

Add a guided Behavior Interview when creating or editing an Agent Profile. Store answers as structured policy, not only as prose. Introduce per-capability autonomy levels: `L0_OBSERVE`, `L1_SUGGEST`, `L2_EXECUTE_SAFE`, `L3_EXECUTE_WITH_GATES`, `L4_AUTONOMOUS`, `L5_OPERATOR`.

The interview covers mission, success criteria, tone, allowed channels, approval-required actions, budgets, privacy, scheduling/proactivity, escalation behavior, and hard prohibitions. Generated policy remains user-visible and editable.

## Acceptance criteria

- [x] Agent Profile stores interview answers and normalized policy separately from generated prompts.
- [x] Autonomy is configurable per capability/tool/action class with explicit inheritance.
- [x] Platform/cluster policy always caps agent-level authority.
- [x] Runtime authorization checks effective autonomy before every tool execution.
- [x] UI provides guided interview, summary, and advanced policy editor.
- [x] Policy changes are audited with actor, timestamp, old value, and new value.
- [x] Tests cover inheritance, denial, approvals, and policy edits.
- [x] Unit tests pass (`python3 -m pytest`).
- [x] `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agents/...`, `backend/app/policy/...`, schemas/routes |
| Frontend | `frontend/src/...` Agent Profile create/edit flow |
| Tests | agent policy and authorization tests |
| Docs | agent/profile policy docs |

## Out of scope

Marketplace distribution of profiles; organization-wide RBAC beyond existing cluster policy.

## Notes

Inspiration: Zoey behavior interviews and FounderOS-style autonomy/permission controls. Recommendation: ADAPT.

Landed on `cursor/local-qwen-desktop-agent`: backend policy store PR #70; interview UI PR #75 (`2852d29`); loop `authorize()` hook PR #72 (`8265560`).
