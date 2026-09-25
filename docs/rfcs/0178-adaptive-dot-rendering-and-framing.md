# RFC-0178: Adaptive dot rendering and persona framing

**Status:** accepted
**Author:** Codex
**Date:** 2026-09-25

**Depends on:** [RFC-0176](0176-shared-dot-appearance-profiles.md)
**Related (do not rewrite):** [RFC-0051](0051-humanoid-presence-runtime.md) (quality presets and reduced motion); [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (`buildFigure(density)` and shape framing); [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (persona silhouettes); [RFC-0175](0175-galaxy-presence-option-chat-waveform-and-advanced-controls.md) (figure and Galaxy field budgets).

## Problem

A strong point-cloud look depends on the silhouette staying legible at the actual display size while glow, point count, and pixel ratio stay within the device's rendering budget. Jarvis has quality presets and per-shape framing, but no shared contract that makes every persona fit consistently across viewport shapes and adapts dot quality without damaging distinctive features. Matching APEX's reported ~300,000 dots is not a useful target by itself; the required quality is a readable figure at a stable frame cost.

## Decision

Extend the shared dot engine with per-shape normalized framing and adaptive fidelity. Each shape resolves a safe fit from its sampled bounds and may tune the viewport margin alongside its existing yaw and position. The engine selects deterministic, spatially distributed samples and quality tiers using the existing performance preset and a bounded frame-time signal. Auto starts at balanced density (0.95), steps down one tier after a rolling frame interval stays above 20 ms for 2 seconds, and recovers after it stays below 17 ms for 8 seconds. A 5-second cooldown separates tier changes. Tiers use the established efficient / balanced / cinematic densities (0.6 / 0.95 / 1.15); the lowest tier lowers pixel ratio and bypasses bloom and post-processing. The figure, field, and RFC-0175 Galaxy star budgets remain separate; no mode may starve the figure samples to decorate its background.

Maintain the same silhouette and dominant features when fidelity changes. `efficient`, `balanced`, `cinematic`, `auto`, and reduced-motion behavior remain user-visible contracts; automatic tuning may lower density, bloom, or pixel ratio but cannot change the selected persona or shape. Resize, aspect-ratio, tab visibility, and WebGL fallback behavior are handled by the shared runtime.

## Acceptance criteria

- [x] Every built-in and custom dot shape declares or resolves a safe normalized frame; automated checks exercise desktop, ultrawide, portrait, and short-window aspect ratios.
- [x] The renderer chooses deterministic spatial samples at each fidelity tier so silhouette edges and gold/flow persona motifs remain represented at reduced density.
- [x] `auto` changes quality only within documented frame-time bounds and uses hysteresis; fixed presets remain predictable.
- [x] Separate figure, field, and Galaxy-star budgets are observable and do not steal samples from one another.
- [x] Resizing does not remount the presence or restart an active RFC-0175 morph; background tabs stop unnecessary animation work.
- [x] The harness exposes frame-time and sample-count summaries while any registered persona shape and performance preset is selected.
- [ ] Windows desktop GPU review signs off visual clarity and sustained performance.
- [x] Reduced motion and WebGL failure keep the current accessible status and fallback behavior.

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/presence/renderers/particleTypes.ts`, `shapes/catalog.ts`, `morphableOrbCloud.ts`, shared dot renderer, `HumanoidPresence.tsx`, `frontend/presence-check.tsx` |
| Tests | Shape framing, deterministic LOD, preset selection, resize/morph preservation, and sample-budget tests |

## Out of scope

A fixed 300,000-dot requirement, new user-facing persona or quality setting, rewriting RFC-0175's budgets or lifecycle, opening a camera, and measuring model/inference latency. GPU acceptance requires the Windows desktop; CI can validate deterministic sampling and quality selection only.

## Notes

Implement after RFC-0176. Use screenshot references for visual review and report CI sampling results separately from desktop GPU and visual sign-off.
