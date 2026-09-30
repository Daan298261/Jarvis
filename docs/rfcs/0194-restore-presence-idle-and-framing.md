# RFC-0194: Restore presence idle free-float and centered framing

**Status:** implemented  
**Amended:** 2026-09-30 — **RFC-0195** overrides idle identity-hide and the 920×680∶480 primary stage. Status stays **implemented** for the #466 crop-protection land. Do **not** flip to a new implemented tick from this amend. Desktop soak stays unchecked.  
**Implemented:** #466 @ `9bd2481211c2e27c17b6229a3468711a732c8b42` (squash; pre-squash yaw-frame harden head `6a236b1`). Restores idle free-float, AABB framing + geometric center offset, Neural/Humanoid aspect lock, and yaw-frame fit offset harden.  
**Residuals:** Desktop GPU / live WebGL soak. After RFC-0195, soak is **viewport-fill + humanoid rest identity**, not free-float-hide vs Ref A. Architect-signed residual; cloud VMs cannot sign off. AC box below stays unchecked.  
**Queue item:** P0 — Presence HUD visual regression (no §58 checkbox was filed for this RFC; residual noted in §59 Decision Log)  
**Author:** Cursor cloud  
**Date:** 2026-09-29

### Amend (2026-09-30) — RFC-0195 overrides idle-hide and the capped stage

**This amend overrides:**

- **Decision 1** (restore `idle` / `waiting` / `offline` → `uMorph` 0 free-float). Rest state is a recognizably humanoid / winning-figure silhouette. Idle may loosen motion/density. Idle must **not** dissolve into an anonymous free cloud. RFC-0195 rest tightness ∈ [0.72, 0.92]; engaged = 1.0.
- **Decision 3** and AC “Neural presence host keeps ~680:480 aspect” as the **primary** stage contract, including the product `width: min(100%, 920px)` / `aspect-ratio: 680 / 480` lock. The avatar fills the available presence viewport. HUD chrome overlays; it does not steal avatar space.

**This amend does not override:** Decision 2 (AABB span + geometric center offset — **crop-protection stays**), yaw-frame fit offset harden, Galaxy as ADD not a lifecycle gate, “do not revert the shared dot engine or RFC-0178 budgets.”

**AC `lifecycleMorphTarget("idle") === 0` is void.** Implementers must not restore that assertion. Full contract: [RFC-0195](0195-visual-acceptance-and-presence-stage.md). Implement lane UX/Desktop; silhouette/framing/bloom on **Grok 4.6**.

## Problem

After #458 (`da60dea`) and #430 framing work, the HUD presence regressed:

1. Idle no longer free-floats (dots/galaxy attract stage). `#458` removed `idle` from free phases so idle always shows the figure — every persona looks like a crushed bust and the RFC-0175 Ref A stage is gone.
2. `normalizedPresenceFitScale` treats bounds as origin-symmetric (`2 * max(|min|, |max|)`), which over-shrinks the humanoid bust and leaves it vertically off-center against the camera look-at.
3. Neural HUD CSS unsets the 680:480 aspect and stretches the WebGL stage to the full orb zone while `ReasoningWeb` stays on a 680×480 viewBox — specialist “dots” and the avatar body no longer share a center.

## Decision

**2026-09-30:** items **1** and **3** are **superseded as the product contract** by [RFC-0195](0195-visual-acceptance-and-presence-stage.md). Item **2** (crop-protection) and item **4** (Galaxy ADD) **stay**. Historical text kept so #466 is auditable.

1. ~~Restore RFC-0175 free phases: `idle`, `waiting`, `offline` → `uMorph` 0 (free-float).~~ **SUPERSEDED.** Rest is a readable winning-figure silhouette (rest tightness ∈ [0.72, 0.92]). Engage still morphs/tightens to 1.0.
2. Replace origin-symmetric fit with AABB span + geometric center offset; MorphablePresenceStage applies the offset so the silhouette centers on the camera look-at / framing position. **KEPT.**
3. ~~Re-constrain Neural (and Humanoid) presence stages to the designed aspect ratio, centered in the host — do not stretch the canvas to arbitrary HUD zone proportions.~~ **SUPERSEDED as the primary stage.** Viewport-fill the presence host. Do not use 920px / 680∶480 as the primary contract. Crop-protection (item 2) still applies when filling.
4. Keep Galaxy stars as the ADD layer (`setGalaxy`); do not gate the lifecycle on Galaxy. **KEPT.**

Do **not** revert the shared dot engine or RFC-0178 budgets. Do not merge until local verification passes; leave merge to CoS/Taco.

## Acceptance criteria

- [x] `lifecycleMorphTarget("idle") === 0` and engaged phases === 1. **#466 land.** **2026-09-30 VOID as the product rest contract** (RFC-0195). Implementers must not restore this assertion.
- [x] Fit helper returns scale in [0.45, 1.35] and a geometric center; humanoid bust centers near camera look-at. **KEPT** (crop-protection).
- [x] Neural presence host keeps ~680:480 aspect and is horizontally/vertically centered. **#466 land.** **2026-09-30 VOID as the primary stage** (RFC-0195 viewport-fill). Do not restore the 920×680∶480 cap as the product stage.
- [x] `node --experimental-strip-types --test frontend/presence-lifecycle.test.mjs` passes (11/11). **#466 land.** RFC-0195 implement must update those tests.
- [x] `npm --prefix frontend run build` (and lint) pass.
- [ ] Galaxy mode still toggles the star layer; physical GPU soak remains desktop residual. Soak target is RFC-0195 (identity at rest + viewport-fill), not free-float-hide.

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
