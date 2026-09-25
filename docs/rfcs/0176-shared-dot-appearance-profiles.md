# RFC-0176: Shared dot appearance profiles

**Status:** accepted
**Author:** Codex
**Date:** 2026-09-25

**Related (do not rewrite):** [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (shape catalog and `ParticleOrb` morph API); [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (13 named persona shapes); [RFC-0138](0138-anzu-orb-custom-ui-generation.md) (custom orb compositions); [RFC-0175](0175-galaxy-presence-option-chat-waveform-and-advanced-controls.md) (one cross-avatar lifecycle and same-cloud morph).

## Problem

Jarvis already represents named presences as `ParticleOrb` samples and renders them through shared WebGL code. However, shape geometry, persona identity, and renderer-wide presentation parameters are not separated into a reusable appearance contract. As the 13 personas and custom looks grow, visual improvements can become shape-specific edits or renderer branches instead of benefiting every dot-based look consistently.

## Decision

Add a shared, declarative dot-appearance profile consumed by the existing presence engine. Keep `buildFigure` / `buildField` responsible for geometry and keep the catalog as the source of shape precedence. The profile supplies persona-specific visual parameters (palette, glow/emission, point scale, and depth softness) while the engine owns shader/material behavior and consumes the canonical presence state. Shared motion cues are specified separately in RFC-0177. Profiles tune a common renderer; they do not create new renderers or change persona selection.

All 13 named persona shapes, `hex_aegis`, the default bust, and RFC-0138 custom compositions must use the same profile contract. Missing or invalid profile data resolves to the current neutral appearance. Existing persisted persona and presentation settings remain compatible.

## Acceptance criteria

- [ ] The shape catalog can resolve a typed optional appearance profile independently from figure/field geometry.
- [ ] Every built-in named persona, suite shape, default bust, and custom preset renders through the shared engine; no persona-specific React renderer or shader branch is introduced.
- [ ] Existing per-orb attributes (`gold`, `light`, `flow`, `size`) continue to work and retain each persona's silhouette and signature motif.
- [ ] Shared engine improvements to glow, depth cues, or material quality apply to all catalog shapes without editing each shape implementation.
- [ ] Unknown/missing profile fields safely use defaults; existing saved persona IDs and custom presets still load.
- [ ] A harness can select each catalog profile and verify geometry, phase, reduced-motion, and WebGL fallback behavior.

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/presence/renderers/particleTypes.ts`, `shapes/catalog.ts`, `shapes/personaShapes.ts`, `morphableOrbCloud.ts`, `HumanoidPresence.tsx`, `frontend/presence-check.tsx` |
| Tests | Presence shape/catalog and presentation renderer tests |

## Out of scope

Changing persona roster, shape precedence, voice bindings, custom-UI generation, the RFC-0175 idle/engaged lifecycle or attention source, and importing APEX's paid humanoid code/artwork. The implementation is Jarvis-owned; APEX is a visual reference only.

## Notes

This contract should be implemented before persona-specific render polish. RFC-0175 continues to own the single-cloud free-float / figure morph and pointer / optional face attract behavior; this RFC does not add a second morph API or camera path.
