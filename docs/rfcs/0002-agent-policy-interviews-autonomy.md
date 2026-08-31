# RFC-0002: Agent policy interviews and per-capability autonomy

**Status:** accepted  
**Queue item:** Agent configuration / autonomy controls  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis needs a user-friendly way to configure persistent specialist behavior without forcing users to hand-author system prompts. A single global autonomy switch is too coarse because an agent may safely research autonomously while publishing, spending money, changing credentials, or sending external messages requires stricter authority.

Autonomy level alone is also not a sufficient risk model. Some actions are irreversible or externally consequential even when they belong to an otherwise low-risk capability. Sending a message, firing a webhook, deleting remote data, changing credentials, powering down a host, purchasing something, or executing an irreversible remote command can create effects that snapshots or local rollback cannot undo.

## Decision

Add a guided Behavior Interview when creating or editing an Agent Profile. Store answers as structured policy, not only as prose. Introduce per-capability autonomy levels: `L0_OBSERVE`, `L1_SUGGEST`, `L2_EXECUTE_SAFE`, `L3_EXECUTE_WITH_GATES`, `L4_AUTONOMOUS`, `L5_OPERATOR`.

The interview covers mission, success criteria, tone, allowed channels, approval-required actions, budgets, privacy, scheduling/proactivity, escalation behavior, and hard prohibitions. Generated policy remains user-visible and editable.

Add a second, orthogonal action-effect classification evaluated at runtime. At minimum, actions expose `reversibility`, `external_side_effect`, `financial_effect`, `credential_effect`, and `destructive_effect` metadata. Policy evaluation uses both capability autonomy and effect risk. High autonomy MUST NOT silently erase an effect-based approval requirement.

By default, irreversible external side effects require an explicit human approval gate. The owner may define narrowly scoped persistent exceptions for a specific action class, integration, account, destination, amount/budget, or workflow; exceptions must be visible, revocable, audited, and bounded rather than implied by a broad autonomy level.

## Acceptance criteria

- [ ] Agent Profile stores interview answers and normalized policy separately from generated prompts.
- [ ] Autonomy is configurable per capability/tool/action class with explicit inheritance.
- [ ] Platform/cluster policy always caps agent-level authority.
- [ ] Runtime authorization checks effective autonomy before every tool execution.
- [ ] Tool/action metadata supports reversibility and external/financial/credential/destructive side-effect classification.
- [ ] Policy evaluation treats effect risk as orthogonal to autonomy level.
- [ ] Irreversible external side effects require approval by default even when the agent has `L4_AUTONOMOUS` or `L5_OPERATOR` for that capability.
- [ ] Persistent approval exceptions are narrowly scoped, user-visible, revocable, and audited with actor, rationale, scope, and expiry/limit where applicable.
- [ ] Decision Inbox entries surface why an action was gated, including reversibility/effect-risk fields.
- [ ] UI provides guided interview, summary, and advanced policy editor.
- [ ] Policy changes are audited with actor, timestamp, old value, and new value.
- [ ] Tests cover inheritance, denial, approvals, effect-risk gates, scoped exceptions, and policy edits.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agents/...`, `backend/app/policy/...`, tool/action metadata, schemas/routes |
| Frontend | `frontend/src/...` Agent Profile create/edit flow, Decision Inbox risk display |
| Tests | agent policy, authorization, irreversible-action gate tests |
| Docs | agent/profile policy docs |

## Out of scope

Marketplace distribution of profiles; organization-wide RBAC beyond existing cluster policy; transactional runtime configuration and post-condition verification, which should remain separate implementation concerns.

## Notes

Initial inspiration: Zoey behavior interviews and FounderOS-style autonomy/permission controls. Recommendation: ADAPT.

2026-08-31 update — Heliox OS v0.13.0 (released 2026-08-27) explicitly tracks irreversibility independently of permission tier and keeps confirmation requirements for effects that cannot be undone by rollback. Source: https://www.helioxos.dev/ and https://github.com/VyomKulshrestha/Heliox-OS. Recommendation: ADAPT STRONGLY. Jarvis is adapting the underlying safety invariant, not Heliox's tier model: authority and consequence risk remain separate axes, with owner-controlled narrow exceptions instead of a blanket hard-coded confirmation rule.
