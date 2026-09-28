# RFC-0189: Impeccable design language for the AI harness

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md). Living index: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #8).  
**Related (do not rewrite):** `PORTAL_UX.md` (Architect-owned shell). RFC-0069 / RFC-0137 / RFC-0175 presence (orb and morph stay those RFCs). RFC-0138 custom UI presets. Daybreak visual system already in the portal.

This file is **specs-only**. Do not vendor `pbakaus/impeccable`. Do not copy licensed third-party skins. Full intent. **No stubs / soft-fail.**

## Problem

When Jarvis or a coding agent authors portal / Daybreak UI, the result drifts into generic template tells (interchangeable type, nested cards, low-contrast text) because there is no design-system procedure in the harness. Impeccable is a skill, a command vocabulary, and deterministic detector rules for that job. Dropping it in as a new theme would repaint Jarvis instead of raising the quality of **AI-authored** UI.

## Goals

- Give the UX lane a design-language pack: durable product notes, critique/audit/polish commands, and the upstream deterministic detectors, applied when an agent **writes or revises** Jarvis UI.
- Generated UI must respect the existing Daybreak / portal system (orange/black shell, current destinations). Impeccable critiques against that system; it does not replace it.
- Detector findings are real: a clean run is evidence the rules passed, and a failed rule blocks “ready” on AI-authored chrome until fixed or explicitly waived with a reason.
- Assets and prompts that ship in product are original or Apache-2.0 upstream text. No stolen licensed skins, icon sets, or brand marks.

## Non-goals

- Restyling the shipping portal as an Impeccable demo, or changing presence morph (RFC-0175) / persona shapes (RFC-0137).
- Vendoring the engine binary or adding the upstream repo as a git submodule in this specs PR.
- Live browser mode against a deployed production site, weakening CSP, or injecting a localhost helper into the owner’s public portal.
- Rewriting `PORTAL_UX.md`. Invented LE / ATO gates. Butler voice copy (this is layout and UI quality, not persona).

## Contract

| Rule | Requirement |
| --- | --- |
| Source | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0). Skill + detector CLI. |
| When | Agent-authored UI diffs (portal, Daybreak, companion chrome an agent is editing) load the skill and run `detect` on the touched files before the change is called done. |
| Product truth | If the implement ticket records audience/constraints, it writes them as project design notes for the agent. Those notes are not the butler system prompt. |
| House style | Detectors may flag generic tells. Waivers for intentional Jarvis choices (brand orange, existing type) are explicit ignore rules with a reason, not a silent disable of the whole pack. |
| Skins | Refuse imports of proprietary themes, paid UI kits, or trademarked character art. Inspiration stays structural. |
| Missing | Pack or detector binary absent ⇒ the authoring job says design-check `unavailable` and does not stamp “polished.” Hand-written owner patches are not blocked by a missing optional pack unless the job claimed the check. |
| Fail | A badge that says audited when the detector did not run. A theme swap presented as this RFC. Licensed skin files in the repo. |

Command names (`audit`, `polish`, `critique`, and the rest of the upstream set) stay the upstream vocabulary inside the skill. Jarvis does not need all 24 commands on day one; the implement ticket must wire **init/context, audit, critique, and polish** for real, and leave the others callable from the same skill rather than stubbed as success.

## Acceptance

- [x] Spec: design pack for AI-authored UI, house style preserved, no licensed skins
- [ ] Implement: an agent UI edit can run the detector and attach findings; failures are not reported as pass
- [ ] Implement: Jarvis brand waivers are listed with reasons; the rest of the rules still run
- [ ] Implement: missing detector ⇒ `unavailable`, not polished
- [ ] Tests: fixture UI with a known rule hit vs a clean fragment (`tests/test_rfc0189_*.py`)
- [ ] No vendored engine and no third-party skins in the specs PR

## Local clone

Not in git.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/rfc/impeccable` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\rfc\impeccable` |

Upstream: https://github.com/pbakaus/impeccable

## Lane

**UX** (how AI-authored Daybreak/portal diffs use the pack). **D1** only for the detector invocation and the pass/fail record on a generation job.

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | agent-authored UI paths under `frontend/src` in the **implement** ticket only |
| Backend | optional job record for detector results |
| Tests | `tests/test_rfc0189_*.py` |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only. Do not edit `PORTAL_UX.md` |

## Out of scope

Presence/morph RFCs. Persona holds (RFC-0104 / RFC-0190). Shipping a visual retheme of the current portal without an agent-authored change.
