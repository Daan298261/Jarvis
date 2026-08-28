# RFC-0005: Isolated parallel coding workers

**Status:** accepted  
**Queue item:** Developer agents / parallel execution  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Multiple coding agents working on the same repository can overwrite each other, corrupt uncommitted work, or produce unreviewable changes if they share a checkout.

## Decision

Every concurrent coding task receives an isolated Git worktree (or equivalent sandbox checkout), dedicated branch, task-scoped filesystem permissions, and its own process environment. A verifier/integrator reviews output before changes may reach the target branch.

## Acceptance criteria

- [ ] Parallel coding tasks cannot write to the same worktree.
- [ ] Jarvis automatically creates and cleans task branches/worktrees.
- [ ] Uncommitted or user-owned changes in the primary checkout are never modified.
- [ ] Each task records base SHA, branch, worktree, commits, tests, and final diff.
- [ ] Integration requires verifier approval or configured human approval.
- [ ] Conflicts are surfaced as Decision Inbox items rather than silently resolved.
- [ ] Tests cover concurrent task isolation and cleanup.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | developer harness, git tool, sandbox manager |
| Tests | parallel worktree/integration tests |
| Docs | coding worker execution contract |

## Out of scope

General non-code sandboxing and swarm scheduling.

## Notes

Inspiration: OpenHands Agent Canvas isolated Git worktrees. Recommendation: ADAPT.
