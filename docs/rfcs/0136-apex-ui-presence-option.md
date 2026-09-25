# RFC-0136: Expose APEX orb-and-graph presence

**Status:** accepted  
**Author:** Codex  
**Date:** 2026-09-25

## Problem

Jarvis already vendors the MIT-licensed APEX-UI orb and reasoning graph and exposes that renderer as “Neural HUD.” The Appearance selector does not identify its upstream visual style, so users following APEX-UI cannot discover the option. The linked repository does not contain the private APEX humanoid figure.

## Decision

Name the existing neural orb-and-graph option “APEX UI · orb + graph” in Appearance, retaining the existing `neural` stored value and renderer for saved settings and compatibility. Clarify the option in assistive text and preserve Jarvis branding and current availability semantics.

## Acceptance criteria

- [ ] Appearance exposes the existing APEX orb + reasoning graph renderer under an explicit selectable label.
- [ ] Existing saved `neural` settings continue to select the same renderer.
- [ ] The label does not imply Jarvis includes APEX’s separately hosted humanoid figure.
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
