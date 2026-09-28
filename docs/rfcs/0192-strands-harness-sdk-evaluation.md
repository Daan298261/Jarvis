# RFC-0192: Strands Harness SDK evaluation

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) Module Catalog Download allowlist. Living index: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #7, inserted after RFC-0188 and before the persona hold).  
**Related (do not rewrite):** RFC-0055 butler. RFC-0155 Coding Missions. RFC-0174 Agent Rooms (Anzu supervises). RFC-0182 keeps the ANZU loop as the owner-turn harness. RFC-0184 Ripwire (code map, not a second loop). RFC-0188 TeamAI (skill sync, not a harness). RFC-0104 / RFC-0190 persona holds — this repo is **not** a member.

This file is **specs-only**. Do not vendor `strands-agents/harness-sdk`. Jarvis/Anzu stays the product orchestrator. **Download ≠ integrate.** Full intent. **No stubs / soft-fail.**

## Problem

A comment-scrape follow-up on the Git Radar reel (batch n29) resolved a caption link that the 2026-09-28 36-URL grid did not score: [strands-agents/harness-sdk](https://github.com/strands-agents/harness-sdk). It is an Apache-2.0 Python and TypeScript SDK for building and controlling an agent harness (model loop, tools, MCP, multi-agent delegation, sessions, memory, skills). The assembled entry points are `create_harness()` (`strands-harness`) and `createHarness()` (`@strands-agents/harness`). Defaults are a full agent: Bedrock Claude, shell and file tools, web fetch, subagents, `./.agent/sessions`, `./.agent/memory`, and `./.agent/skills`, plus a `strands` CLI.

Without a child RFC, a worker will either drop the link or install that default agent in place of butler, Dual Seat, the portal, or the ANZU plan → act → verify loop.

## Goals

- Score the SDK with a written research result, then expose an optional Module Catalog **Download** row under the RFC-0095 allowlist.
- Lock the sidecar shape now, so a later ticket cannot invent a second orchestrator. Code for that shape waits until the research result is `partial` and CoS names the follow-up.
- Jarvis/Anzu remains the only product orchestrator. Coding Missions (RFC-0155) and Agent Rooms (RFC-0174) stay the owner-visible mission surfaces.
- Capability stays truthful: no harness result, no “running” chip, and no tool schema while the SDK is only downloaded.

## Non-goals

- Replacing the butler persona (RFC-0055), Dual Seat, or the portal (Daybreak owner chat and shell) with Strands’ agent, `HARNESS_CONTRACT` prompt, `strands` CLI, or any Strands-hosted UI.
- A `persona_candidate` tag. This is a library, not a full-assistant product (RFC-0104 / RFC-0190).
- Vendoring the monorepo, or adding `strands-agents` / `strands-harness` to Jarvis backend requirements.
- Pip-install, process spawn, Bedrock, or any cloud model key as part of Download.
- Turning on upstream shell, file write, web, Exa search, subagents, skills, session files, or `./.agent/memory` inside a Jarvis turn.
- A second approval modal. RFC-0110 remains the only owner approval surface. Strands `interventions` are not wired here.
- Reopening RFC-0182. Owner turns keep the ANZU loop. This SDK is not the context-segmentation harness.
- Invented LE / Red / Purple / ATO gates. Exploit or attack-step docs.

## What the upstream is

Monorepo (Apache-2.0), studied at `c56b7dea985c0c596ab021c46d3d4d15b4c35b67`. Packages the evaluation must name, not copy:

| Package | Role |
| --- | --- |
| `harness-py` / `strands-harness` | Assembled Python agent, `create_harness()` |
| `strands-py` / `strands-agents` | Python SDK loop, tools, `OpenAIModel` |
| `harness-ts`, `strands-ts` | TypeScript equivalents. Reference only. Not a second portal. |
| `strands-cli` | `strands` terminal chat. Not owner chat. |
| `strands-mcp` | Upstream MCP server package. Not Jarvis’s MCP client. |

`create_harness()` documents overrides the sidecar pattern relies on: `builtin_tools=[]`, `builtin_plugins=[]`, `memory=False`, `skills=False`, `session=False`, and a `Model` instance instead of the Bedrock default. `OpenAIModel` accepts `client_args`, including `base_url`, so a local OpenAI-compatible endpoint is the intended model wire. Confirming a live call against Jarvis inference is desktop sign-off. The default Bedrock model string is not a Jarvis configuration.

## Research result (implement ticket)

D1 writes the result into a **Research result** section of this RFC (same file, no master-plan rewrite) after reading the local clone. Answer each item. Do not leave them as “TBD”.

1. **Local model.** Can a stripped `OpenAIModel(client_args={"base_url", "api_key"})` target the owner’s already-running Jarvis OpenAI-compatible endpoint (llama.cpp / the configured inference host)? If the only working path is Bedrock, Anthropic, Gemini, or another cloud key, the result is `archive_only`.
2. **No second authority.** With `builtin_tools=[]`, `builtin_plugins=[]`, `memory=False`, `skills=False`, `session=False`, and subagent omitted, confirm the process does not start a shell, write `./.agent/`, or fetch the web. If those switches do not actually disable the defaults, the result is `archive_only`.
3. **MCP overlap.** Record what `mcp_servers` and `strands-mcp` add beyond Jarvis MCP. Do not connect a server in this ticket.
4. **Multi-agent overlap.** Record `subagent` / `Agent.as_tool()` against RFC-0174 rooms. Rooms stay the owner-visible collaboration surface. Delegation inside Strands stays off in the sidecar pattern.
5. **Coding missions.** A later sidecar may receive a bounded brief from RFC-0155 and return a bounded result. It does not own the worktree, merge, or push. Say whether the SDK can run in that shape.
6. **License and process.** Apache-2.0 allows a separate process. Vendoring into Jarvis git is still forbidden. The Python packages are the only sidecar candidate. TypeScript and the CLI stay reference.
7. **Recommendation.** Exactly one of `archive_only` or `partial`. `whole` and `persona_candidate` are not outcomes.

The catalog allowlist below is not gated on `partial`. Download is for study either way. A sidecar process is gated on `partial` plus a later CoS-named ticket.

## Contract — catalog Download (this implement ticket)

| Rule | Requirement |
| --- | --- |
| Identity | Catalog entry id `harness-sdk`, slug `harness-sdk`. Integrate decision **`review`**. Not `whole`, not `partial`, not `persona_candidate`. |
| Upstream | Allowlisted `source_url` only: `https://github.com/strands-agents/harness-sdk` |
| Discover | RFC-0095 path order: recorded `local_path`, then Windows `jarvis-ig\rfc\harness-sdk`, Architect `/workspace/projects/rfc/harness-sdk`, then other RFC-0095 library roots. Do not scan the disk. |
| Download | Existing RFC-0095 clone or zip into that library slug. Record `local_path`, source URL, resolved commit, timestamp. Refuse any other remote. |
| After Download | Library-local only. Do not pip-install, do not import `strands` inside `backend/app`, do not spawn, do not flip integrate away from `review`. |
| Status | `missing` / `found` / `error`. No `starting` / `running`. No Start/Stop. |
| Tools | Jarvis tool registry unchanged when the row is present or downloaded. |
| Butler / seats / portal | Butler prompt fixtures, Dual Seat, and portal routes unchanged. |
| Fail | Download that installs into the Jarvis environment. A chip that says running because an import succeeded. A Strands page, CLI tab, or owner-chat mode. A non-allowlisted URL accepted. |

## Contract — sidecar pattern (locked; not this ticket’s code)

Apply only after the research result is `partial` and CoS names the follow-up. Until then these rows are the boundary, not a hidden implement list.

| Rule | Requirement |
| --- | --- |
| Process | Separate environment, out of process. One bounded invocation per mission step. Jarvis supervises. No resident agent and no Strands UI. |
| Who calls | Jarvis, from a Coding Mission step or an Agent Room specialist slot. The sidecar does not subscribe to owner chat. |
| Model | Only the owner’s already configured OpenAI-compatible Jarvis endpoint, via `OpenAIModel` `client_args` `base_url`. No Bedrock default. No new API key. |
| Disabled | `builtin_tools=[]`, `builtin_plugins=[]`, `memory=False`, `skills=False`, `session=False`, subagent off, `mcp_servers` unset, `interventions` unset. |
| In / out | In: a bounded mission brief. Out: bounded text, stop reason, package version, model id. Jarvis verifies. Strands does not merge, speak, write the vault, or write skills. |
| Missing | SDK absent or research still `archive_only`: Coding Missions and Agent Rooms run unchanged. No fabricated result. |
| Fail | Importing Strands as `backend/app/agent`’s loop. `strands` CLI as owner chat. `HARNESS_CONTRACT` replacing the butler prompt. Shell or web tools enabled. `./.agent/memory` as a second vault. A non-loopback listener. Dual Seat or the portal swapped for a Strands session. |

## Acceptance

- [x] Spec: seven research questions, catalog allowlist, sidecar boundary, Download ≠ integrate, Jarvis/Anzu stays orchestrator
- [ ] Implement: Research result section answers all seven numbered items; recommendation is `archive_only` or `partial`
- [ ] Implement: allowlisted Download for `harness-sdk` only; record path, URL, and commit; integrate stays `review`
- [ ] Implement: Download does not pip-install, import Strands into the backend, or spawn a process
- [ ] Tests: foreign URL refused; tool registry unchanged; butler prompt fixtures unchanged; no child process (`tests/test_rfc0192_*.py`)
- [ ] Live stripped-harness call against a local GGUF, if the research section needs one, is Windows desktop sign-off
- [ ] No vendored tree in the specs PR or the implement PR

## Local clone

Not in git. Comment-scrape follow-up already cloned it for study.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/rfc/harness-sdk` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\rfc\harness-sdk` |

Upstream: https://github.com/strands-agents/harness-sdk

## Lane

**D1.** Research result first, then the optional Module Catalog Download allowlist under the RFC-0095 pattern. No portal replacement. Existing catalog controls (Download, path, Open folder) are enough if the implement ticket surfaces the row. Do not add a Strands screen.

## Likely files

| Area | Paths |
| --- | --- |
| Research | this RFC, new **Research result** section |
| Backend | RFC-0095 allowlist registration (`register_allowlisted_source` in `backend/app/modules/catalog_download.py`, called from the catalog source table) |
| Tests | `tests/test_rfc0192_*.py` |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only |

## Out of scope

Wiring the sidecar process (separate ticket after `partial`). RFC-0184 map. RFC-0188 skill sync. RFC-0174 room protocol changes. Persona merge. Model-stack changes. Bulk catalog RFC-0096–0104.
