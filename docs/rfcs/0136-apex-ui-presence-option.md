# RFC-0136: Expose APEX orb-and-graph presence

**Status:** accepted  
**Amended:** 2026-09-30 — [RFC-0195](0195-visual-acceptance-and-presence-stage.md) makes this naming **mandatory** in product copy and forbids presenting APEX as the Jarvis **humanoid** reference. Status stays **accepted** (do not flip implemented from this amend). Numbering collision: installer zombie-kill is the other `0136-zombie-kill-setup-next-and-start.md`; **this file** is the APEX presence option.  
**Author:** Codex  
**Date:** 2026-09-25

## Problem

Jarvis already vendors the MIT-licensed APEX-UI orb and reasoning graph and exposes that renderer as “Neural HUD.” The Appearance selector does not identify its upstream visual style, so users following APEX-UI cannot discover the option. The linked repository does not contain the private APEX humanoid figure.

## Decision

Name the existing neural orb-and-graph option **“APEX UI · orb + graph”** in Appearance, retaining the existing `neural` stored value. Assistive text must say this is the **public MIT APEX-UI orb and reasoning graph**, adapted for Jarvis, and that Jarvis **does not** include APEX’s separately hosted private humanoid. **RFC-0195:** this control is a **style/profile** on the shared presence renderer, not a competing humanoid stage. Stop presenting APEX as the humanoid reference.

## Acceptance criteria

- [ ] Appearance exposes the existing APEX orb + reasoning graph renderer under an explicit selectable label.
- [ ] Existing saved `neural` settings continue to select the same renderer.
- [ ] The label does not imply Jarvis includes APEX’s separately hosted humanoid figure.
- [ ] Preview for this control matches the live orb-and-graph profile (RFC-0195 accurate previews), not a humanoid bust thumbnail.
- [ ] Frontend production build succeeds.

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/settings/AppearanceSettingsPane.tsx` |

## Out of scope

- Reimplementing the private APEX humanoid figure.
- Replacing Jarvis presence modes or adding a duplicate renderer/settings value.
- Changing upstream vendored components or their license attribution.

## Notes

- Upstream: https://github.com/RubenM1990/APEX-UI
- The existing APEX component source and MIT attribution are already present under `frontend/src/vendor/apex-ui/` and `frontend/third_party/APEX-UI/`.
