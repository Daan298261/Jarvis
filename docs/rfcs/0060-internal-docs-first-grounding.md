# RFC-0060: Internal docs-first grounding

**Status:** accepted  
**Queue item:** P1 — Internal docs-first grounding  
**Author:** Jarvis Architect  
**Date:** 2026-09-09

## Problem

When users ask about Jarvis itself, hit on-screen errors, or are in a new-install / post-version-bump window, the chat model often guesses instead of reading local product references. That produces wrong answers about Jarvis's own behavior, APIs, install paths, settings, and UI.

## Decision

Add a chat-pipeline **DocsFirstGrounding** gate that, when triggered, retrieves from local project/Jarvis internal references **before** general world knowledge or unconstrained generation about Jarvis itself.

### Trigger heuristics

Fire when **any** of the following match (prefer false-negatives over blocking normal chat):

1. **System-about:** query is about the Jarvis product/self — capabilities, architecture, how to use, settings, ports, models, swarm, installer, errors, "what is Jarvis", "how do I…". Implement as lightweight classifier or keyword+intent rules.
2. **On-screen error:** active UI/error context is attached (toast, crash dialog, stderr snippet, HTTP error banner) **or** the user pastes an error clearly from Jarvis.
3. **New-install / version-bump budget:** first ~100 user chat requests after a detected version bump or fresh install (see budget counter below).

When triggered: if screen/error context is available, include it in the retrieval query; then search local references before answering.

### Path contract (canonical roots)

Prefer these roots in order (all read-only from the agent's view; implementers may add aliases):

| Priority | Root | Notes |
| --- | --- | --- |
| 1 | `project/jarvis/jarvis/internal/references/**` | Preferred product/internal references tree; create empty scaffold with README only if needed for path contract |
| 2 | In-repo docs that ship with Jarvis | `docs/**`, root `*.md` product specs the runtime may index — **index allowlist**, not whole-repo dump (`AGENTS.md`, `docs/PROCESS.md`, `INSTALL*.md`, `WINDOWS_SHELL.md`, `ANDROID_CLIENT.md`, etc.) |
| 3 | Packaged `internal/references` | Under install prefix when running from an installed build |

Retrieval must be **local-first**. Do not call external web search for these triggers unless local hit confidence is low **and** the query is not "about Jarvis itself" (for self-about, never exfiltrate; stay local).

### Request-budget counter

Persist `docs_first_budget`: `{ version: string, remaining: int }` (default `remaining=100` on version change / first run).

- Decrement once per user chat turn when the docs-first gate ran (not per retrieval hop).
- When `remaining` hits 0 and no other trigger matches, gate is off until next version bump.
- System-about and on-screen-error triggers still fire after budget exhausts.

### Privacy / no exfil

- Reference corpus and screen/error context stay on-device / on-LAN.
- Never upload reference corpus, screen captures, or error blobs to third-party providers solely for grounding.
- If the active inference backend is remote, only send the **minimal retrieved snippets** needed for the answer (token-capped), not whole files; redact secrets/credentials found in local docs.
- No telemetry of doc contents.

### API / hooks (chat pipeline)

Sketch integration points (names may match existing modules):

- Pre-answer hook in agent loop / chat pipeline: `maybe_docs_first(context) -> GroundingBundle | None`
- **Inputs:** user message, optional UI error context, app version, budget state
- **Outputs:** ranked snippets + source paths + citation ids for the prompt
- **Prompt policy:** when `GroundingBundle` present, instruct model to prefer cited local refs over guessing; admit gaps rather than invent Jarvis behavior
- **Optional tool:** `search_internal_references(query)` restricted to allowlisted roots

Relate lightly to RFC-0020 (project knowledge) and RFC-0011 (context repos) but this RFC is **product-self grounding**, not user project workspaces.

## Acceptance criteria

- [ ] Trigger heuristics documented and implemented as deterministic rules + optional light classifier
- [ ] Path contract allowlist enforced; searches cannot escape roots
- [ ] Budget counter persists across restarts; resets on version bump
- [ ] System-about / error triggers work with `budget=0`
- [ ] Privacy: no external fetch for self-about; redaction of secrets in snippets
- [ ] Chat pipeline hook returns citations; answers that used grounding can cite paths
- [ ] Unit tests for triggers, budget, path confinement, redaction
- [ ] Unit tests pass (`python3 -m pytest`); no portal required for MVP of this RFC

## Likely files

| Area | Paths |
| --- | --- |
| Backend | agent loop / chat pipeline hook, `search_internal_references` tool, retrieval module |
| Settings | thin `docs_first_budget` persistence |
| Tests | `tests/test_docs_first_grounding.py` (triggers, budget, path confinement, redaction) |
| Docs | `project/jarvis/jarvis/internal/references/` scaffold if missing |

## Out of scope

Full RAG product for user projects (RFC-0020); web search UX; Astra UI redesign; installer changes; rewriting `JARVIS_MASTER_PLAN.md`.

## Notes

Complements RFC-0020 (user project workspaces) and RFC-0011 (context repositories) without replacing them. Desktop sign-off optional for live retrieval quality against a populated references tree.
