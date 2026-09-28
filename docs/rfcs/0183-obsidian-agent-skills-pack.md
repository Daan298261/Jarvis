# RFC-0183: Obsidian agent skills pack

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) umbrella. Living index: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #1).  
**Deepens:** [RFC-0107](0107-obsidian-linked-memory-brain.md) (linked vault + embedded real Obsidian). Does not replace the 0107 embed residual.  
**Related (do not rewrite):** RFC-0011 ContextRepo. RFC-0090 Install now. RFC-0099 OpenViking/RAGFlow. RFC-0100 research crawl. RFC-0116 / RFC-0171 Jev. RFC-0132 Supermemory. RFC-0173 Skill Forge. RFC-0185 ai-memory sidecar.

This file is **specs-only**. Do not vendor `kepano/obsidian-skills`. Do not build a custom brain UI. Full intent. **No stubs / soft-fail.**

## Problem

RFC-0107 binds an owner vault and hosts the real Obsidian UI, but Jarvis agents still improvise Obsidian Flavored Markdown, Bases, JSON Canvas, and the official CLI. A bound vault whose writes are generic Markdown, or a “skills connected” chip that never calls the CLI or the open formats, leaves the brain half-taught. The 2026-09-28 reel (“Hermes + Obsidian memory”) is this gap plus the existing [RFC-0104](0104-persona-candidates-pack.md) Hermes hold — not a new persona merge.

## Goals

- Teach Jarvis and vault-touching agents the upstream Agent Skills pack: Obsidian Flavored Markdown, Bases (`.base`), JSON Canvas (`.canvas`), and the official Obsidian CLI (open, plugin, theme operations the owner asked for).
- Optional Defuddle (clean Markdown from a page) and Knap (template render from JSON/CSV) run only when the owner ask needs them, under the same network and filesystem policy as today.
- Skills resolve from the local clone (or an RFC-0095 allowlisted Download of that repo). Record clone commit and skill names in provenance.
- Vault Markdown on disk stays the human canonical store (RFC-0107). Skill text is procedure, not a second vault.

## Non-goals

- A custom note browser, graph viewer, or “Jarvis brain” editor. Owner surface remains embedded official Obsidian (RFC-0107).
- Replacing RFC-0107 watch / index / working-set. This pack is how agents speak Obsidian’s formats and CLI.
- Vendoring the skills tree into Jarvis git. Butler, voice, or system-prompt merge. A Hermes persona (RFC-0104 stays tag-only).
- Making Defuddle a second research crawler (RFC-0100 stays the crawl connector). Invented LE / Red / Purple / ATO gates. Exploit recipes.

## Contract

| Rule | Requirement |
| --- | --- |
| Source | [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills). Agent Skills layout (`skills/<name>/SKILL.md`). |
| Register | Skill pack id `obsidian-skills`, enabled only when the clone is present **and** a vault is bound. Status is `missing` / `found` / `enabled` / `error`. Missing pack or missing Obsidian CLI → real Download / install CTA. |
| Use | On a vault write or “open in Obsidian / follow that link / make a base / make a canvas” ask, the agent follows the matching skill against the bound vault. Wikilinks, embeds, callouts, and properties are first-class, not stripped. |
| CLI | `obsidian-cli` drives the official CLI. If the CLI is down, RFC-0107 file watch/index/act still works. That is not permission to fake CLI success. |
| Defuddle / Knap | Opt-in for that turn. Defuddle output is a candidate note, not an automatic vault dump. Knap renders into the vault only when the owner asked to generate files. |
| Authority | Jarvis orchestrates. Obsidian remains the editor. ContextRepo remains structured memory. |
| Fail | Enabled pack that never changes tool choice on a vault ask. Writes that ignore Obsidian syntax the skill exists to produce. A React markdown pane shipped as the skill surface. A chip that says the pack is live when the clone is absent. |

Upstream install notes (Claude/Codex/OpenCode skill folders) are for external harnesses. Jarvis loads the same `SKILL.md` files through its skill registry. Do not require a second coding-agent install for the owner vault path.

## Acceptance

- [x] Spec names the pack, the six upstream skills, and the no-custom-UI rule
- [ ] Implement: vault-format and CLI skills are invocable from a bound vault; provenance stores clone commit
- [ ] Implement: missing clone or missing CLI is a truthful CTA, and retrieval/watch from RFC-0107 still runs
- [ ] Implement: Defuddle and Knap do not run unless the ask needs them; Defuddle obeys existing network policy
- [ ] Tests cover enabled-vs-missing pack and a managed note that keeps wikilinks / properties (`tests/test_rfc0183_*.py`)
- [ ] No product code in the specs PR; no vendored skills tree

## Local clone

Not in git.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/rfc/obsidian-skills` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\rfc\obsidian-skills` |

Upstream: https://github.com/kepano/obsidian-skills

## Lane

**D1** (skill registry, vault tool routing, CLI adapter, tests). **UX** only for a truthful pack status row on the existing vault/settings surface — not a new editor.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/memory/obsidian_vault.py`, skill registry / `backend/app/skills/` (implement ticket) |
| Frontend | existing vault/settings status only — no custom brain UI |
| Tests | `tests/test_rfc0183_*.py` |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only |

## Out of scope

RFC-0107 embed residual (Top 10 #8 — finish that before bulk catalog). RFC-0185 agent-memory sidecar. Persona merge of Hermes. Jev (RFC-0116 / RFC-0171).
