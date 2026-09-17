# RFC-0104: Persona candidates pack (tag only / later personality)

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; personality track is a later named ticket)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** RFC-0055 butler / social commentary persona. RFC-0061 / 0062 / 0070 / **0092** voice. RFC-0067 owner-chat chrome. Do **not** merge these repos into the household butler.

This PR is **specs-only**. Do not commit local clones. **No persona merge.**

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clones (already downloaded; **do not commit**). Path pattern: `/workspace/projects/persona/<name>`.

**Every entry below is a full AI assistant / agent harness** (explicit). Catalog tag: **`persona_candidate`**. They are **not** Jarvis modules to wire into the butler in this track.

| Name | Kind | Canonical | Local path |
| --- | --- | --- | --- |
| hermes-agent | **Full AI assistant / self-improving agent** | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | `/workspace/projects/persona/hermes-agent` |
| openhuman | **Full AI assistant / local-first harness** | [tinyhumansai/openhuman](https://github.com/tinyhumansai/openhuman) | `/workspace/projects/persona/openhuman` |
| F.R.I.D.A.Y | **Full AI assistant** (Iron-Man-class companion clone; inspiration only) | [just-innovative-bro/F.R.I.D.A.Y](https://github.com/just-innovative-bro/F.R.I.D.A.Y) | `/workspace/projects/persona/friday` |
| deer-flow | **Full AI assistant / research-agent harness** | [bytedance/deer-flow](https://github.com/bytedance/deer-flow) | `/workspace/projects/persona/deer-flow` |
| openclaude | **Full AI assistant / coding-agent harness** | [Gitlawb/openclaude](https://github.com/Gitlawb/openclaude) | `/workspace/projects/persona/openclaude` |
| opencode | **Full AI assistant / coding-agent harness** | [sst/opencode](https://github.com/sst/opencode) | `/workspace/projects/persona/opencode` |
| locally-uncensored | **Full AI assistant / local studio** (chat + gen + coding agent) | [PurpleDoubleD/locally-uncensored](https://github.com/PurpleDoubleD/locally-uncensored) | `/workspace/projects/persona/locally-uncensored` |

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** under `/workspace/projects/persona/<name>`. Not vendored. Not installed into Jarvis Python. |
| 2. Usefulness review | **Score 3/5 as inspiration.** Primary bucket: **`persona` / `persona_candidate`**. Not `mas_integration`. Not `module` for v1. |
| 3. Integrate decision | **`persona_candidate` later** — tag only. **No** `whole` or `partial` merge into butler, system prompt, or voice. Taco can override to `archive_only`; **must not** override to butler-merge without a new personality-track RFC. |
| 4. Implement | **Not now.** Later **personality pack** track (separate RFC after Taco names it). This file is the scored hold. |

## Problem

RFC-0095 forbids folding full-assistant GitHub saves into Jarvis butler voice/persona. Without a child RFC, implementers treat hermes-agent / openhuman / F.R.I.D.A.Y / deer-flow / openclaude / opencode / locally-uncensored as drop-in personalities or second orchestrators. They are **complete products**. Merging them would fork Jarvis, fight RFC-0055/0092, and risk uncensored/jailbreak studio defaults (locally-uncensored) or Marvel/Iron Man clone tone (F.R.I.D.A.Y).

## Decision

**Tag-only pack** for the later personality track.

1. Catalog entries: `persona_candidate`, pipeline stage `review` / `decide` = **later**. Integrate recommendation: **`persona_candidate` (later)** — not `whole`, not `partial` into butler.
2. **No merge** into: default system prompt, RFC-0055 commentary persona, RFC-0061/0062/0070/0092 voice packs, owner-chat greeting, Daybreak HUD copy.
3. **No second orchestrator:** do not register these as Jarvis workers that replace the Leader loop. Optional later: extract **patterns** (memory UX, skill files, HUD ideas) into original Jarvis code under a named personality RFC — still not a tree merge.
4. **F.R.I.D.A.Y / Marvel / Iron Man:** feel is not a clone. Same rule as RFC-0092 Codsworth. Archive for tone notes only.
5. **locally-uncensored:** full local studio + uncensored defaults. Stay `persona_candidate` / likely `archive_only` for product; do not import jailbreak/uncensored policy into household Jarvis.
6. Module Catalog Download (RFC-0095) may still clone/zip for the owner library. Download ≠ integrate.

**Architect’s initial recommendation:** `persona_candidate` later (no butler merge). Taco can override per-repo to `archive_only`. Butler merge requires a **new** RFC.

**Will not:** merge any of these into butler; vendor trees; rewrite RFC-0092; stand up a second Jarvis; offensive tools.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (`/workspace/projects/persona/<name>`; clones not committed)
- [x] Usefulness review — spec’d (3/5 inspiration; `persona_candidate`; each row marked **full AI assistant**)
- [x] Integrate decision — spec’d (`persona_candidate` later; no butler merge; Taco may override to archive_only)
- [ ] Implement (personality track) — later named ticket **after** Taco/CoS promote it (not this PR, not 0096–0103 implement tickets)
- [ ] Catalog tags exist in the RFC-0095 module catalog design (`persona_candidate`; no persona merge)
- [ ] Specs-only in this PR
- [ ] No product code that copies these assistants into prompts/workers in this PR

## Likely files

| Area | Paths |
| --- | --- |
| Backend (later personality PR only) | RFC-0095 module catalog entries (`backend/app/api/modules.py` when 0095 is implemented) — tags only |
| Frontend (later) | Module Catalog row badges: `persona_candidate` |
| Tests | later `tests/test_rfc0104_*.py` — tag present; butler prompt fixtures unchanged |
| Docs | this RFC; §59 batch line only |

## Out of scope

**Any butler/persona/voice merge.** Product implementation of 0096–0103. HexStrike. Offensive tools (Strix / Pentagi / Claude-Red stay LE-gated under RFC-0095 — **no child RFC**). Vendoring these trees. Marvel/Iron Man/Codsworth clones.

## Notes

- Parent RFC-0095 reserved this number and the name list. This child **writes the scored hold**; it does not open a personality implementation ticket.
- Implement (when named): personality track only; do not fold into RFC-0092 or 0055; PR against `development`.
