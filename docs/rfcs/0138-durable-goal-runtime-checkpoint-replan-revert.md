# RFC-0138: Durable Goal Runtime — plan, execute, evaluate, re-plan, revert

**Status:** accepted  
**Date:** 2026-09-24

## Problem

Anzu has tasks, schedules and agents, but needs a first-class long-running objective runtime comparable to modern goal/workflow systems: durable progress, evaluation, pause/resume and safe recovery across crashes.

## Decision

Introduce Goal as a durable object above tasks. Lifecycle: DRAFT → PLANNED → RUNNING → EVALUATING → COMPLETED, with PAUSED/BLOCKED/FAILED/CANCELLED. A planner decomposes an objective into a dependency graph with success criteria. The executor delegates bounded work to agents/workflows. An evaluator compares artifacts/results against explicit criteria and chooses complete, retry, re-plan or ask owner. Re-planning preserves the audit trail instead of rewriting history.

Checkpoint after every state transition and side-effect boundary. Resume is idempotent. Revert restores Anzu-owned state/artifacts from snapshots where possible; external side effects are never falsely “rolled back” and instead get compensating-action proposals plus approval. Existing approval, scheduler, Decision Inbox and policy gates remain authoritative.

UI: Goals workspace with graph/timeline, current step, blockers, approvals, artifacts, cost/resources, checkpoints and pause/resume/revert controls.

## Acceptance criteria

- [ ] Durable goal schema, task DAG, criteria and append-only transition journal.
- [ ] Crash/restart resumes from last safe checkpoint without duplicate side effects.
- [ ] Evaluation can complete/retry/re-plan/block; bounded retry/loop detection prevents runaway execution.
- [ ] Pause/resume/cancel/revert are explicit and auditable.
- [ ] External effects use compensating actions and approvals, never fake rollback.
- [ ] Goals can invoke agents, workflows and schedules through existing gates.
- [ ] UI exposes progress, artifacts, decisions, cost and checkpoints.
- [ ] Tests cover crash recovery, duplicate prevention, failed evaluation, re-plan and approval suspension.

## Likely files

`backend/app/goals/`, task/scheduler integration, DB migrations, `frontend/src/`, `tests/test_goal_*.py`.
