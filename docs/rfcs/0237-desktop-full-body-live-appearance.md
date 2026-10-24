# RFC-0237: Full-body personas and live appearance controls

**Status:** accepted

**Author:** Codex, requested by Daan

**Date:** 2026-10-24

## Problem
Persona heads sit too low behind the composer, legacy variants expose unwanted procedural masks, and nested appearance settings hide immediate render-mode selection. Galaxy can remain overridden by Daybreak state.

## Decision
Preserve the existing humanoid artwork, geometry, motion, and default presentation exactly. Extend named-persona artwork into complete animated particle bodies: a standing stag for Eir, birds for Anzu/Nabu/Bragi, a dragon for Veles, and complete mythic figures for the other portraits. Retain the authored heads. Fit the complete persona into the visible stage above the composer, including on smaller windows. Make full body the persona default; remove legacy choices and migrate saved legacy persona selections. Expose Daybreak, Galaxy, Humanoid, and Persona avatar directly in the left Appearance menu with immediate preview; selecting a visual mode must not remain trapped behind a Daybreak visual override. Bughunt within these appearance, framing, and render transitions.

## Acceptance criteria
- All named personas have complete finite point-cloud bodies with their original head artwork and bounded coherent motion.
- Eir has a standing deer body, four legs and hooves, with the pictured head.
- Head, antlers/crowns and feet remain visible above the composer at desktop and smaller viewport sizes.
- The existing humanoid's source geometry/artwork and rendered appearance remain unchanged.
- Legacy choices are absent from both left controls and full Appearance settings.
- The four requested render options are immediately available in the left Appearance menu; edits remain visible without leaving the HUD.
- Galaxy renders and remains selected across mode switches, including switching away from Daybreak.
- Focused geometry, controls and transition regressions; frontend build/lint; required backend checks; browser and installed-desktop verification pass.

## Likely files
Frontend presence shapes/rigging, persona variant selection, HUD appearance controls and persona-only stage framing; focused frontend tests. No architect-owned specification changes.

## Out of scope
Changes to the preserved humanoid or unrelated backend tools. Stable/main promotion.
