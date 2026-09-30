# RFC-0031: Reversibility-first action gates

**Status:** implemented  
**Implemented:** #476 @ `a50c7adf7c2f8467e51c464520e7b83b8915dc90` on `development` (squash). Authorize → RFC-0027 firewall hook → reversibility / unforgeable `ApprovalGrant` / park-resume / durable undo with real filesystem + settings reverse executors; `snapshot_required` fail-closed; undo registration failures observable (no silent `except: pass`).  
**Residuals (do not claim done):** full RFC-0027 privacy-gateway / REDACT re-eval / egress detector (ordering hook only in #476); portal/HUD undo chrome; terminal/apps reverse executors (honest `not_implemented` until wired); Desktop live soak (irreversible pause → ApprovalGrant → resume with real model).  
**Queue item:** P1 — owner control / autonomy UX (no §58 checkbox was filed for this RFC; residual noted in §59 Decision Log)  
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

- [x] Every side-effecting tool/action exposes `reversibility` plus required recovery/compensation metadata; `UNKNOWN` is never treated as safely reversible by default. **#476**
- [x] Runtime authorization and RFC-0027 firewall evaluation occur before reversibility handling; reversibility cannot turn a policy/firewall deny into allow. **#476** (firewall ordering hook; full privacy gateway residual below)
- [x] Policy-permitted low-risk `REVERSIBLE` actions can execute without an approval interruption and create a durable undo record linked to task/run/step IDs. **#476**
- [x] `COMPENSATABLE` actions declare the compensation operation, its preconditions, and whether compensation itself has external effects. **#476**
- [x] `IRREVERSIBLE`/`UNKNOWN` and policy-defined high-consequence effects route to Decision Inbox or an equivalent explicit human gate. **#476**
- [x] A human approval contains action ID, exact scope/target, origin channel, actor/session, timestamp, expiry, policy version, and decision. **#476** (`ApprovalGrant`)
- [x] Model/tool arguments such as `confirmed`, `approve`, or `yes` can never create or satisfy a human approval grant. **#476**
- [x] Pending approval parks the durable step without holding an inference/worker loop; confirm/reject/timeout resumes or terminates the same step. **#476**
- [ ] Undo can be invoked from UI and natural language and shows exactly what operation will be reversed. **Residual:** backend `/api/reversibility/*` preview/apply + Decision Inbox park text landed; portal/HUD undo chrome and NL undo surface not in #476.
- [x] Undo re-validates preconditions/current state and returns a visible conflict when safe reversal is no longer possible. **#476**
- [x] Bulk/composite actions retain per-child recovery records and can compensate completed children in reverse dependency order. **#476**
- [x] Undo history is bounded/configurable and does not retain unbounded file blobs or secrets; large-state recovery uses snapshots/references where supported. **#476**
- [x] Audit records show original action, approval (if any), undo/compensation request, outcome, and conflicts without exposing secret payloads. **#476**
- [x] Tests prove a model cannot self-confirm an irreversible action by choosing tool parameters. **#476** (`tests/test_rfc0031_reversibility_gates.py`)
- [x] Tests cover reversible file/settings actions, destructive/credential/external gates, timeout/reject, stale undo preconditions, and composite rollback. **#476**
- [x] Unit tests pass (`python3 -m pytest`). **#476** land claimed green; unrelated tip failures reproduce on bare `development`.
- [ ] If portal/HUD is touched, `npm --prefix frontend run build` passes. **Residual:** `frontend/` not in #476; portal undo chrome still open.

### Residual notes (unchecked — do not mark implemented)

- Full RFC-0027 privacy-gateway / REDACT re-eval / egress detector remains a **separate** ticket (`semantic_firewall.py` is an ordering hook only).
- Portal/HUD undo chrome / UI (UX lane).
- Terminal / apps compensatable reverse executors: apply refuses with honest `not_implemented` until concrete reverse executors exist (filesystem + settings restores are wired).
- Desktop live sign-off / soak: irreversible pause → `ApprovalGrant` → resume on Windows with a real model. Cloud VMs cannot sign this off.

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

**Land evidence (#476):** `backend/app/policy/{reversibility,reversibility_gate,approval_grant,undo_journal,undo_restore,semantic_firewall}.py`, `backend/app/api/reversibility.py`, agent-loop wiring, `tests/test_rfc0031_reversibility_gates.py`. Peer APPROVE_WITH_RESIDUALS blockers closed on pre-squash head `fca13da7` (real undo reverse, `snapshot_required` fail-closed, no silent undo-register swallow).
