# RFC-0190: Persona hold — Pi Desktop agent workspace

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; not an implement ticket until Taco promotes it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0104](0104-persona-candidates-pack.md) persona-candidate pattern. Umbrella: [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md).  
**Living index:** [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #10 — catalog badge only).  
**Related (do not rewrite):** RFC-0055 butler. RFC-0092 voice. RFC-0137 named persona presence. RFC-0175 presence morph (reference only if a later UX ticket wants motion notes).

This file is **specs-only**. Tag only. **Download ≠ integrate.** No butler / voice merge. Do not vendor `DLYZZT/pi-desktop`.

## Problem

Pi Desktop is a full local agent workspace (Electron shell, Pi Coding Agent, sessions, skills, managed processes, its own browser, chat channels). Saved next to Jarvis it looks like a personality or a second desktop to embed. RFC-0104 already forbids that class of merge; this reel item was not in the original pack, so a worker can still treat it as a module.

## Goals

- Add Pi Desktop to the RFC-0104 hold: catalog tag `persona_candidate`, pipeline stage later, integrate decision **not** `whole` or `partial`.
- Module Catalog may Download the clone and show a badge. The badge states hold / not integrated.
- Patterns (workspace layout, session list) stay inspiration until Taco names a personality-track RFC.

## Non-goals

- Merging Pi’s system prompt, skills, WeChat/Telegram/Feishu channels, or `~/.pi/agent` store into Jarvis butler, voice, or owner chat.
- Embedding the Electron app, spawning Pi as a second orchestrator, or importing its browser policy.
- A UI morph or humanoid clone. Presence work stays RFC-0175 / RFC-0069. Any “humanoid assistant” reel without a repo is `needs_link` on the integration list, not this product.
- Vendoring the tree. Invented LE / ATO gates. Turning the hold into an implement ticket in this PR.

## Contract

| Rule | Requirement |
| --- | --- |
| Identity | Catalog id `pi-desktop`. Kind: **full AI assistant / desktop agent workspace**. |
| Upstream | [DLYZZT/pi-desktop](https://github.com/DLYZZT/pi-desktop) (Apache-2.0). |
| Tag | `persona_candidate`. Recommendation: later. Taco may override to `archive_only` only. Butler merge needs a new RFC. |
| Download | RFC-0095 Download may clone or zip into the persona library. Success records `local_path` and commit. It does not enable a worker. |
| Badge | Portal/catalog row, when RFC-0095’s catalog exists: name, tag, path, Open folder. No “Use as Jarvis” action. |
| Fail | Any copy of Pi prompts into Jarvis system prompts. A worker registration. A silent skill import (that would be RFC-0188 with an explicit owner opt-in, still not a persona merge). |

## Acceptance

- [x] Spec: `persona_candidate`, Download ≠ integrate, no butler/voice merge
- [x] Listed on the RFC-0104 pattern via this child RFC (0104 notes point here; the original seven-row table stays)
- [ ] Later catalog ticket: badge only, no worker, butler prompt fixtures unchanged
- [ ] Tests, when the catalog exists: tag present; no Pi strings in the default system prompt (`tests/test_rfc0190_*.py`)
- [ ] No product code and no vendored tree in the specs PR

## Local clone

Not in git.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/persona/pi-desktop` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\persona\pi-desktop` |

Upstream: https://github.com/DLYZZT/pi-desktop

## Lane

**Later** (Architect / UX catalog badge only until Taco promotes). No D1 worker in this hold.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | RFC-0095 catalog entry only, in a future catalog ticket |
| Frontend | badge only, same ticket |
| Tests | `tests/test_rfc0190_*.py` when that ticket exists |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only |

## Out of scope

Personality-track implementation. RFC-0188 sync of Pi skills. RFC-0183 Hermes/Obsidian wiring. Presence morph.
