# RFC-0178: Adaptive dot rendering and persona framing

**Status:** accepted
**Author:** Codex
**Date:** 2026-09-25

**Depends on:** [RFC-0176](0176-shared-dot-appearance-profiles.md)
**Related (do not rewrite):** [RFC-0051](0051-humanoid-presence-runtime.md) (quality presets and reduced motion); [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (`buildFigure(density)` and shape framing); [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (persona silhouettes); [RFC-0175](0175-galaxy-presence-option-chat-waveform-and-advanced-controls.md) (figure and Galaxy field budgets).

## Problem

A strong point-cloud look depends on the silhouette staying legible at the actual display size while glow, point count, and pixel ratio stay within the device's rendering budget. Jarvis has quality presets and per-shape framing, but no shared contract that makes every persona fit consistently across viewport shapes and adapts dot quality without damaging distinctive features. Matching APEX's reported ~300,000 dots is not a useful target by itself; the required quality is a readable figure at a stable frame cost.

## Decision

Extend the shared dot engine with per-shape normalized framing and adaptive fidelity. Each shape declares a fit target / safe bounds in addition to its existing yaw and position. The engine selects deterministic, spatially distributed samples and quality tiers using the existing performance preset, canvas size, device pixel ratio, and a bounded frame-time signal. Hysteresis prevents quality oscillation. The figure, field, and RFC-0175 Galaxy star budgets remain separate; no mode may starve the figure samples to decorate its background.

Maintain the same silhouette and dominant features when fidelity changes. `efficient`, `balanced`, `cinematic`, `auto`, and reduced-motion behavior remain user-visible contracts; automatic tuning may lower density, bloom, or pixel ratio but cannot change the selected persona or shape. Resize, aspect-ratio, tab visibility, and WebGL fallback behavior are handled by the shared runtime.

## Acceptance criteria

- [ ] Every built-in and custom dot shape declares or resolves a safe normalized frame; automated checks show no figure is clipped at supported desktop, ultrawide, portrait, or short-window aspect ratios.
- [ ] The renderer chooses deterministic spatial samples at each fidelity tier so eyes/face, silhouette edges, and defining persona motifs remain represented at reduced density.
- [ ] `auto` changes quality only within documented frame-time bounds and uses hysteresis; fixed presets remain predictable.
- [ ] Separate figure, field, and Galaxy-star budgets are observable and do not steal samples from one another.
- [ ] Resizing does not remount the presence or restart an active RFC-0175 morph; background tabs stop unnecessary animation work.
- [ ] The harness records frame-time and sample-count summaries for every persona at each preset; Windows desktop GPU review signs off visual clarity and sustained performance.
- [ ] Reduced motion and WebGL failure keep the current accessible status and fallback behavior.

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/presence/renderers/particleTypes.ts`, `shapes/catalog.ts`, `morphableOrbCloud.ts`, shared dot renderer, `HumanoidPresence.tsx`, `frontend/presence-check.tsx` |
| Tests | Shape framing, deterministic LOD, preset selection, resize/morph preservation, and sample-budget tests |

## Out of scope

A fixed 300,000-dot requirement, new user-facing persona or quality setting, rewriting RFC-0175's budgets or lifecycle, opening a camera, and measuring model/inference latency. GPU acceptance requires the Windows desktop; CI can validate deterministic sampling and quality selection only.

## Notes

Implement after RFC-0176. Use screenshot references for visual review and report CI sampling results separately from desktop GPU and visual sign-off.
