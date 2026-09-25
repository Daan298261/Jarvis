# RFC-0176: Shared dot appearance profiles

**Status:** implemented
**Implemented:** #428 @ `7ecfdcf0128c8e67d4ece8aef6af8ed4ca66977c` (shared appearance profiles; bounded point scale and depth softness).
**Specs:** #426 @ `d792ed4749bfc5857e8f1a55435b2b4d99714d28`.
**Quality bar:** **Anzu 1.0**. Full intent. No stubs / soft-fail.
**Residuals:** none. The catalog-profile harness row is checked. #433 @ `a128942e7849cec9ceeb8eabb04e70d4b44dcd83` closed it: shared profile controls and the cross-shape preview added in #430 cover geometry, phase, reduced-motion, and WebGL fallback. The #428 body reported the frontend build and focused presence checks passing.
**Author:** Codex
**Date:** 2026-09-25

**Related (do not rewrite):** [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (shape catalog and `ParticleOrb` morph API); [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (13 named persona shapes); [RFC-0138](0138-anzu-orb-custom-ui-generation.md) (custom orb compositions); [RFC-0175](0175-galaxy-presence-option-chat-waveform-and-advanced-controls.md) (one cross-avatar lifecycle and same-cloud morph).

### Quality bar

The implement is **multibillion-company grade** and the user-facing stretch is **Anzu 1.0**. Profiles tune the existing shared renderer. A persona-specific shader branch, a second renderer, or a profile that drops silhouette and motif attributes is a **fail**. Full intent. No stubs / soft-fail.

## Problem

Jarvis already represents named presences as `ParticleOrb` samples and renders them through shared WebGL code. However, shape geometry, persona identity, and renderer-wide presentation parameters are not separated into a reusable appearance contract. As the 13 personas and custom looks grow, visual improvements can become shape-specific edits or renderer branches instead of benefiting every dot-based look consistently.

## Decision

Add a shared, declarative dot-appearance profile consumed by the existing presence engine. Keep `buildFigure` / `buildField` responsible for geometry and keep the catalog as the source of shape precedence. The profile supplies persona-specific visual parameters (palette, glow/emission, point scale, and depth softness) while the engine owns shader/material behavior and consumes the canonical presence state. Shared motion cues are specified separately in RFC-0177. Profiles tune a common renderer; they do not create new renderers or change persona selection.

All 13 named persona shapes, `hex_aegis`, the default bust, and RFC-0138 custom compositions must use the same profile contract. Missing or invalid profile data resolves to the current neutral appearance. Existing persisted persona and presentation settings remain compatible.

## Acceptance criteria

- [x] The shape catalog can resolve a typed optional appearance profile independently from figure/field geometry.
- [x] Every built-in named persona, suite shape, default bust, and custom preset renders through the shared engine; no persona-specific React renderer or shader branch is introduced.
- [x] Existing per-orb attributes (`gold`, `light`, `flow`, `size`) continue to work and retain each persona's silhouette and signature motif.
- [x] Shared engine improvements to glow, depth cues, or material quality apply to all catalog shapes without editing each shape implementation.
- [x] Unknown/missing profile fields safely use defaults; existing saved persona IDs and custom presets still load.
- [x] A harness can select each catalog profile and verify geometry, phase, reduced-motion, and WebGL fallback behavior.

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/presence/renderers/particleTypes.ts`, `shapes/catalog.ts`, `shapes/personaShapes.ts`, `morphableOrbCloud.ts`, `HumanoidPresence.tsx`, `frontend/presence-check.tsx` |
| Tests | Presence shape/catalog and presentation renderer tests |

## Out of scope

Changing persona roster, shape precedence, voice bindings, custom-UI generation, the RFC-0175 idle/engaged lifecycle or attention source, and importing APEX's paid humanoid code/artwork. The implementation is Jarvis-owned; APEX is a visual reference only.

## Notes

This contract should be implemented before persona-specific render polish. RFC-0175 continues to own the single-cloud free-float / figure morph and pointer / optional face attract behavior; this RFC does not add a second morph API or camera path.

Product landed on development via #428 @ `7ecfdcf0128c8e67d4ece8aef6af8ed4ca66977c`. Specs were #426 @ `d792ed4749bfc5857e8f1a55435b2b4d99714d28`. Quality bar stays **Anzu 1.0**. The harness acceptance row is closed by #433 @ `a128942e7849cec9ceeb8eabb04e70d4b44dcd83` (covered by the #430 shared profile controls and cross-shape preview). No residual.
