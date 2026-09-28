# RFC-0188: TeamAI CLI skill and rules sync

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md). Living index: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #6).  
**Adjacent:** Module Catalog (RFC-0095), skill lifecycle (RFC-0024), [RFC-0173](0173-skill-forge-verified-trace-to-reusable-skill.md) Skill Forge.  
**Related (do not rewrite):** RFC-0183 Obsidian skills (one pack, not the sync bus). RFC-0184 Ripwire (code map). RFC-0104 persona hold.

This file is **specs-only**. Do not vendor `Tencent/teamai-cli`. Do not replace the Jarvis skill store. Full intent. **No stubs / soft-fail.**

## Problem

Skills and rules that Jarvis forges or the owner writes die inside one harness. TeamAI is a git-native sync of skills, rules, and related harness files across coding agents. Pointing Jarvis at it without a contract would either ignore the bus or let an external repo overwrite the Jarvis skill store.

## Goals

- Optional TeamAI CLI sidecar: **sync** skills and rules the owner opted in to publish or pull, via a git remote the owner chose.
- Jarvis skill store (RFC-0024 / RFC-0173) stays canonical for skills Jarvis runs. TeamAI is the exchange format for **other** coding agents and for owner-approved import/export.
- Status is truthful: no remote, no CLI, or a failed pull is an error, not “synced.”
- Provenance on every import: remote URL, commit, path, and the Jarvis skill id it mapped to.

## Non-goals

- Replacing Skill Forge, the module catalog, or butler/voice prompts.
- Auto-push of household persona, system prompts, secrets, or unapproved traces.
- Team wiki, usage dashboard, or session analytics (upstream beta). Those wait for a later RFC.
- Vendoring the npm package into Jarvis git. Invented LE / ATO gates.
- Treating Hermes, Pi, or any other listed upstream agent as a merged Jarvis persona (RFC-0104 / RFC-0190).

## Contract

| Rule | Requirement |
| --- | --- |
| Source | [Tencent/teamai-cli](https://github.com/Tencent/teamai-cli) (MIT). Owner-installed `teamai` CLI. |
| Remote | Owner-supplied git URL with credentials from the existing secret store (references, not copied into skill files). |
| Direction | **Pull** and **push** are explicit owner actions (or a setting that names which skill ids may auto-pull). Default is no automatic push. |
| Map | Imported skills land as candidate or versioned Jarvis skills under RFC-0024/0173 review. They do not silently replace the active version. |
| Export | Only skill ids the owner marked shareable. Rules files the same way. Exclude `.env`, license keys, and memory dumps. |
| Conflict | If the Jarvis active version and the remote commit disagree, surface both and wait. No silent overwrite. |
| Missing | CLI or remote absent ⇒ sync status `missing` / `error`. Local skills keep working. |
| Fail | A sync chip with no commit recorded. A push of the butler prompt. A second skill authority that Forge writes do not update. |

Module Catalog may offer Download of the TeamAI clone and a “set team repo” field. Download ≠ turning sync on.

## Acceptance

- [x] Spec: git sync beside the skill store; store stays canonical; no silent push
- [ ] Implement: explicit pull creates a reviewable skill version with remote commit provenance
- [ ] Implement: explicit push sends only owner-marked ids; secrets paths are refused
- [ ] Implement: conflict does not clobber the active skill; missing CLI does not report synced
- [ ] Tests for pull, refuse-secret, and conflict (`tests/test_rfc0188_*.py`)
- [ ] No vendored tree in the specs PR

## Local clone

Not in git.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/rfc/teamai-cli` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\rfc\teamai-cli` |

Upstream: https://github.com/Tencent/teamai-cli

## Lane

**D1** (CLI adapter, skill import/export, tests). **UX** for a Module Catalog / Skill Forge sync row (status, remote, pull, push) — not a new skill runtime.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | skill store / Forge publish path; settings for the team remote |
| Frontend | catalog or Forge sync controls in the implement ticket |
| Tests | `tests/test_rfc0188_*.py` |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only |

## Out of scope

Rewriting RFC-0173. Obsidian skill content (RFC-0183). Code maps (RFC-0184). Persona merge.
