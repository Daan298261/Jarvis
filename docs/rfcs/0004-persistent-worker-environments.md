# RFC-0004: Persistent worker environments

**Status:** accepted  
**Queue item:** Persistent workers / runtime state  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Long-lived specialist agents lose time and continuity if each task reconstructs files, packages, browser state, caches, and working context from scratch.

## Decision

Allow selected workers to own a persistent runtime environment with durable workspace files, package environment/container, caches, browser profile, process metadata, scoped credentials, task state, and logs. Environment lifetime is independent from any individual LLM request.

Credentials must be capability-scoped and revocable. A worker environment may be suspended and resumed without changing the logical Agent Profile.

## Acceptance criteria

- [ ] Worker runtime has durable workspace identity and lifecycle: create, start, suspend, resume, reset, delete.
- [ ] Persistent state survives Jarvis restart where supported.
- [ ] Credentials are stored outside plain workspace files and scoped to the worker/capability.
- [ ] Resource quotas can cap disk, CPU, RAM, GPU, and background processes.
- [ ] UI exposes environment status, disk usage, last active time, reset, and inspect actions.
- [ ] Audit log records environment and credential lifecycle events.
- [ ] Tests cover lifecycle and safe cleanup.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | worker/runtime manager, credential broker, workspace service |
| Frontend | worker environment detail view |
| Tests | runtime lifecycle tests |
| Docs | persistent environment design |

## Out of scope

Cross-node migration; that belongs to Agent Runtime Portability.

## Notes

Inspiration: Manus Cloud Computer, adapted to local/self-hosted Jarvis workers. Recommendation: ADAPT.
