# RFC-0001: Development process and one-ticket worker loop

**Status:** implemented  
**Queue item:** (process hygiene — no product queue line)  
**Author:** Cursor cloud agent  
**Date:** 2026-08-25

## Problem

Vague worker prompts caused repeated full-repo audits, wholesale **Current State** rewrites, colliding branches, and attempts to merge superseded PRs. Design specs were pasted into `JARVIS_MASTER_PLAN.md` instead of small, implementable tickets.

## Decision

Encode a durable process in `docs/PROCESS.md`, `docs/rfcs/`, and `AGENTS.md`:

- Design → short RFCs under `docs/rfcs/` (one concern each).
- Implementation → one named RFC or one queue item per Cursor run, branching from `cursor/local-qwen-desktop-agent`.
- Master plan → architecture + §57–58 summary only; updated after merge, not before design.
- Close superseded PR #25; document in `docs/PROCESS.md`.

## Acceptance criteria

- [x] `docs/PROCESS.md` describes the one-ticket loop
- [x] `docs/rfcs/TEMPLATE.md` exists
- [x] `AGENTS.md` tells workers how to start
- [x] Linux/cloud cannot sign off Windows/GPU P0 is documented
- [x] PR #25 marked superseded (closed on GitHub)
- [x] `python3 -m pytest` still passes

## Likely files

| Area | Paths |
| --- | --- |
| Process | `docs/PROCESS.md`, `docs/rfcs/README.md`, `docs/rfcs/TEMPLATE.md` |
| Agent bootstrap | `AGENTS.md` |
| Doc index | `docs/README.md`, `README.md` |

## Out of scope

- Browser Use, swarm, P4/P5, model-stack changes
- Rewriting `JARVIS_MASTER_PLAN.md` architecture sections

## Notes

Canonical repo: **Daan298261/Jarvis**. Integration branch: **cursor/local-qwen-desktop-agent**.
