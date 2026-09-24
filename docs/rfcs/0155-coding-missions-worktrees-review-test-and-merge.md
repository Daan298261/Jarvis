# RFC-0155: Coding Missions — isolated worktrees, review, test and merge

**Status:** accepted  
**Date:** 2026-09-24

## Problem
A coding specialist needs a production workflow, not unrestricted edits in the user's working tree.

## Decision
Add Coding Mission as a specialized Goal. It creates/uses an isolated branch/worktree, inspects repo instructions, drafts a plan, edits incrementally, runs allowed tests/lints/builds, requests critic/reviewer agents for meaningful changes, summarizes diffs and only merges/pushes under owner policy. Preserve uncommitted owner changes. Support GitHub issue/PR context through connectors. Failed missions remain inspectable/resumable.

## Acceptance criteria
- [ ] Worktree/branch isolation and dirty-tree protection.
- [ ] Test/build commands are repo-configured or explicitly approved; no arbitrary guessed destructive commands.
- [ ] Reviewer/critic can block completion with actionable findings.
- [ ] Diff, test evidence, commits and unresolved failures are shown before merge.
- [ ] Resume after crash without duplicate commits/pushes.
- [ ] Enki persona and Goal Runtime can launch missions.

## Likely files
Coding agent, Git integration, Goals, Artifact Workspace, GitHub connector UI/tests.
