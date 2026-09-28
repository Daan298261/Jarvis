# RFC-0184: Ripwire coding-agent context map

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md). Living index: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #2).  
**Related (do not rewrite):** RFC-0085 fast path (expose only tools the turn needs). RFC-0155 Coding Missions. RFC-0158 context compiler. RFC-0173 Skill Forge. RFC-0188 TeamAI sync (skills bus, not a code map).

This file is **specs-only**. Do not vendor `redhat-et/ripwire`. Jarvis stays the orchestrator. Full intent. **No stubs / soft-fail.**

## Problem

Coding turns still pay for whole-file reads when the question is “what should change, what breaks, which tests reach it.” Jarvis has filesystem, git, and Coding Missions, and no optional **codebase map** that answers before the agent opens every file. Without a named contract, a worker will either ignore the map or replace the Jarvis loop with the upstream binary.

## Goals

- Optional local Ripwire sidecar: CLI first, MCP second, so a coding agent receives a ranked, bounded map (what to touch, blast radius, tests that reach the edit) without reading the repo into the prompt.
- Jarvis plans, calls tools, and verifies. Ripwire is a map provider for that turn.
- Capability is truthful: map tools appear only when the binary answers. A missing binary leaves Coding Missions, git, and filesystem working.
- Install is an owner-approved, checksum-aware path (catalog Download of the clone and/or a pinned upstream release). Record version and commit.

## Non-goals

- Replacing Playwright, git, the filesystem tool, or RFC-0155’s worktree/review/merge policy.
- A daemon or graph database as a requirement. Upstream is one offline process with no API key; keep that shape.
- Vendoring the C++ tree or shipping `curl | bash` as Jarvis’s default installer.
- Putting MCP verb schemas in every chat prompt when the turn is not a coding map ask (CLI is the cheap path).
- Invented LE / Red / Purple / ATO gates. Exploit or attack-step docs.

## Contract

| Rule | Requirement |
| --- | --- |
| Source | [redhat-et/ripwire](https://github.com/redhat-et/ripwire) (Apache-2.0). Languages and limits stay upstream’s; Jarvis does not reimplement the call graph. |
| Interface | Prefer `ripwire <repo> --for="<owner ask>"` (and the upstream edit/check verbs the task needs). Optional MCP only if the owner enables it. |
| When | Coding Missions and other repo-editing turns that need structure call the map **before** bulk file reads. The working set stores the bounded answer plus the command and version. |
| Honesty | Truncation, floors, and “none found” stay labeled as the tool reported them. Jarvis must not rewrite a partial map into a claim that the repo was fully read. |
| Missing | Status `missing`. Offer RFC-0095 Download / pinned install. Do not invent a fake graph. Do not block non-coding chat. |
| Authority | Jarvis tool policy (allowlisted repo roots, RFC-0155 owner merge rules) still wraps every later edit and shell call. Ripwire does not gain a bypass. |
| Fail | A coding turn that advertises a map while the binary is absent. A prompt stuffed with the whole tree “because the map was short.” An MCP server started on a non-loopback interface by default. |

Token budget on the map call is the implementer’s knob: the turn asks for a complete-enough answer and records when the tool says it overflowed. Silent row drops are a fail.

## Acceptance

- [x] Spec locks CLI-first optional map, Jarvis as orchestrator, truthful absence
- [ ] Implement: a coding turn can request a map and place a bounded excerpt in the working set with version provenance
- [ ] Implement: missing binary → `missing` + Download/install CTA; git/filesystem/Coding Missions still run
- [ ] Implement: MCP, if enabled, binds loopback and is not injected into non-coding turns
- [ ] Tests: present vs absent binary; excerpt is bounded; no claim of a full-repo read (`tests/test_rfc0184_*.py`)
- [ ] No vendored tree in the specs PR

## Local clone

Not in git.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/rfc/ripwire` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\rfc\ripwire` |

Upstream: https://github.com/redhat-et/ripwire

## Lane

**D1** (optional worker, coding-mission pre-read, tests). No portal NLE or chat redesign.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | coding mission / context compiler call site; new `backend/app/workers/` or tools adapter for the CLI |
| Tests | `tests/test_rfc0184_*.py` |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only |

## Out of scope

Bulk Module Catalog (RFC-0095–0104). RFC-0183 vault skills. RFC-0188 team skill sync. Model-stack changes.
