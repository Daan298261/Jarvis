# RFC-0031: Reversibility-first action gates

**Status:** accepted  
**Queue item:** P1 — owner control / autonomy UX  
**Author:** ChatGPT competitor-review synthesis  
**Date:** 2026-09-06

## Problem

Jarvis should require human approval only when the consequence warrants it. RFC-0002 already separates capability authority from effect risk, RFC-0027 adds a semantic action firewall, and RFC-0029 defines durable execution/replay semantics, but the runtime still needs one concrete user-facing invariant: safely reversible actions should normally execute without interrupting the owner, while irreversible or high-consequence actions must be gated by an approval that the model cannot manufacture itself. A tool parameter such as `confirmed=true` is not proof of human approval because the model controls tool arguments.

## Decision

Add a reversibility-first execution contract at the side-effect boundary.

Every side-effecting action declares an effect/recovery class such as `REVERSIBLE`, `COMPENSATABLE`, `IRREVERSIBLE`, or `UNKNOWN`, plus any snapshot/compensation requirements and limits. After ordinary authorization and the SemanticActionFirewall allow the action, low-risk `REVERSIBLE` actions may execute immediately and must durably register how to undo them. `COMPENSATABLE` actions may follow the same path only when the compensation is well-defined and policy permits it. `IRREVERSIBLE`, `UNKNOWN`, financial, credential, destructive, or consequential external effects continue through Decision Inbox / explicit approval policy.

Human approval must have authenticated provenance outside model-generated parameters. The runtime stores an `ApprovalGrant`/equivalent with action ID, user/session identity, origin channel, scope, expiry, and decision. Only trusted UI/physical-user channels may satisfy a human gate. A model re-calling a tool with a boolean/string confirmation parameter can never satisfy it.

Approval UI is non-blocking: park the action and release the worker/model while waiting. On confirm, resume the same durable execution step; on reject/timeout, cancel that step. Do not spend an extra model round trip merely to ask the model to re-submit the same action.

Undo/compensation history is tied to durable execution records rather than an in-process closure stack. Composite actions journal child effects so a bulk operation can reverse completed children in safe reverse order. Before applying an undo, re-check current state/preconditions; if the world has changed and reversal is unsafe, surface a conflict instead of forcing a destructive rollback.

## Acceptance criteria

- [ ] Every side-effecting tool/action exposes `reversibility` plus required recovery/compensation metadata; `UNKNOWN` is never treated as safely reversible by default.
- [ ] Runtime authorization and RFC-0027 firewall evaluation occur before reversibility handling; reversibility cannot turn a policy/firewall deny into allow.
- [ ] Policy-permitted low-risk `REVERSIBLE` actions can execute without an approval interruption and create a durable undo record linked to task/run/step IDs.
- [ ] `COMPENSATABLE` actions declare the compensation operation, its preconditions, and whether compensation itself has external effects.
- [ ] `IRREVERSIBLE`/`UNKNOWN` and policy-defined high-consequence effects route to Decision Inbox or an equivalent explicit human gate.
- [ ] A human approval contains action ID, exact scope/target, origin channel, actor/session, timestamp, expiry, policy version, and decision.
- [ ] Model/tool arguments such as `confirmed`, `approve`, or `yes` can never create or satisfy a human approval grant.
- [ ] Pending approval parks the durable step without holding an inference/worker loop; confirm/reject/timeout resumes or terminates the same step.
- [ ] Undo can be invoked from UI and natural language and shows exactly what operation will be reversed.
- [ ] Undo re-validates preconditions/current state and returns a visible conflict when safe reversal is no longer possible.
- [ ] Bulk/composite actions retain per-child recovery records and can compensate completed children in reverse dependency order.
- [ ] Undo history is bounded/configurable and does not retain unbounded file blobs or secrets; large-state recovery uses snapshots/references where supported.
- [ ] Audit records show original action, approval (if any), undo/compensation request, outcome, and conflicts without exposing secret payloads.
- [ ] Tests prove a model cannot self-confirm an irreversible action by choosing tool parameters.
- [ ] Tests cover reversible file/settings actions, destructive/credential/external gates, timeout/reject, stale undo preconditions, and composite rollback.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal/HUD is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | tool/action metadata, policy/execution boundary, approval service, recovery/undo service |
| Durable runtime | GoalRun/ExecutionStep integration from RFC-0029 |
| Frontend | Decision Inbox confirmation surface, task/history undo affordance, optional HUD pending-action banner |
| Tests | approval provenance, reversibility/compensation, undo conflict and composite-action tests |
| Docs | tool effect/recovery contract |

## Out of scope

Replacing RFC-0002 autonomy policy; replacing RFC-0027 semantic firewall; re-specifying RFC-0029 crash durability; pretending every third-party external action can be made exactly reversible; copying a third-party implementation.

## Notes

Reference reviewed: `FatihMakes/Mark-LII`, especially its `core/undo.py` and UI-issued confirmation pattern. The useful product lesson is **reversible-by-default execution + unforgeable human approval provenance**, not its Python implementation. The source repository is licensed CC BY-NC 4.0, so Jarvis should implement this independently rather than copy/vendor that code into a potentially commercial Jarvis distribution.

Recommendation: **ADAPT STRONGLY**.
