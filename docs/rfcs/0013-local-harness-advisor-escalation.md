# RFC-0013: Compact local harness and advisor escalation

**Status:** implemented  
**Queue item:** Local agent harness optimization  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Smaller/local models lose reliability when exposed to oversized system prompts, huge tool catalogs, and unbounded context. Jarvis also needs a safe way to ask stronger cloud models for help without handing them direct execution authority.

## Decision

Create a compact local-agent harness with: minimal core system prompt, on-demand skill/tool loading, explicit context compaction, deterministic orchestration around the model, and fail-closed sandbox requirements for autonomous tool use.

Add an `Advisor` interface. An advisor may receive a policy-approved context package and return analysis/recommendations/structured plans, but cannot directly invoke Jarvis tools, access files, spend money, or mutate state. The local Orchestrator retains execution authority.

## Acceptance criteria

- [x] Core prompt and core tool surface are independently measurable/versioned.
- [x] Tools/skills are loaded dynamically from task requirements and policy.
- [x] Context compaction produces a provenance-linked summary plus retained critical facts.
- [x] Autonomous execution fails closed when required sandboxing is unavailable.
- [x] Advisor request shows exactly what context/data will leave the local system.
- [x] Advisor has no direct Jarvis capability token or tool-call channel.
- [x] Router can escalate locally failed/low-confidence tasks to advisor under policy/cost limits.
- [x] Tests cover tool-surface restriction, compaction, sandbox failure, and advisor authority isolation.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | agent harness, tool registry, context manager, advisor provider |
| Frontend | disclosure/approval and routing settings |
| Tests | harness/advisor security tests |
| Docs | local harness contract |

## Out of scope

Implementing a specific commercial cloud provider beyond the generic interface.

## Notes

Inspiration: Perplexity Portable Computer/local-first agent architecture. Recommendation: ADAPT STRONGLY.

Landed on `cursor/local-qwen-desktop-agent`: backend PR #67 (`1d614a0`) — new files; advisor has no tools; no harness/compaction rewrite; portal UI PR #83 (`ee745f9`).
