# RFC-0194: Restore presence idle free-float and centered framing

**Status:** accepted  
**Queue item:** P0 — Presence HUD visual regression  
**Author:** Cursor cloud  
**Date:** 2026-09-29

## Problem

After #458 (`da60dea`) and #430 framing work, the HUD presence regressed:

1. Idle no longer free-floats (dots/galaxy attract stage). `#458` removed `idle` from free phases so idle always shows the figure — every persona looks like a crushed bust and the RFC-0175 Ref A stage is gone.
2. `normalizedPresenceFitScale` treats bounds as origin-symmetric (`2 * max(|min|, |max|)`), which over-shrinks the humanoid bust and leaves it vertically off-center against the camera look-at.
3. Neural HUD CSS unsets the 680:480 aspect and stretches the WebGL stage to the full orb zone while `ReasoningWeb` stays on a 680×480 viewBox — specialist “dots” and the avatar body no longer share a center.

## Decision

1. Restore RFC-0175 free phases: `idle`, `waiting`, `offline` → `uMorph` 0 (free-float). Engaged phases keep the winning figure.
2. Replace origin-symmetric fit with AABB span + geometric center offset; MorphablePresenceStage applies the offset so the silhouette centers on the camera look-at / framing position.
3. Re-constrain Neural (and Humanoid) presence stages to the designed aspect ratio, centered in the host — do not stretch the canvas to arbitrary HUD zone proportions.
4. Keep Galaxy stars as the ADD layer (`setGalaxy`); do not gate the lifecycle on Galaxy.

Do **not** revert the shared dot engine or RFC-0178 budgets. Do not merge until local verification passes; leave merge to CoS/Taco.

## Acceptance criteria

- [x] `lifecycleMorphTarget("idle") === 0` and engaged phases === 1.
- [x] Fit helper returns scale in [0.45, 1.35] and a geometric center; humanoid bust centers near camera look-at.
- [x] Neural presence host keeps ~680:480 aspect and is horizontally/vertically centered.
- [x] `node --experimental-strip-types --test frontend/presence-lifecycle.test.mjs` passes (11/11).
- [x] `npm --prefix frontend run build` (and lint) pass.
- [ ] Galaxy mode still toggles the star layer; physical GPU soak remains desktop residual.

## Likely files

| Area | Paths |
| --- | --- |
| Lifecycle | `frontend/src/presence/presenceLifecycle.ts` |
| Framing | `frontend/src/presence/presenceQuality.ts`, `MorphablePresenceStage.tsx`, `shapes/humanoidBust.ts` |
| Neural layout | `frontend/src/presence/renderers/apex-presence.css`, `humanoid-presence.css` |
| Tests | `frontend/presence-lifecycle.test.mjs` |
| Docs | this RFC; optional internal ref note |

## Out of scope

Desktop GPU soak, webcam face attract sign-off, rewriting RFC-0175/0178, Android companion APK visuals.
