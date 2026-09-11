# RFC-0069: Presence shape catalog and morph API

**Status:** implemented
**Author:** Jarvis Architect
**Date:** 2026-09-10

**Related:** RFC-0050 (presence architecture / `avatarId`), RFC-0051 (humanoid runtime), implement [PR #166](https://github.com/Daan298261/Jarvis/pull/166), parity [PR #165](https://github.com/Daan298261/Jarvis/pull/165)

## Problem

#165 landed visual parity for the particle humanoid (thousands of glowing orbs, not a mesh). Shape morphing and a multi-shape catalog were unspecified. Implementers shipped #166 ahead of this RFC. This RFC locks the accepted contract to that surface so specs can land, then #166, without churn.

## Decision

Accept the #166 catalog + morph surface. Names must match the code. Do **not** invent a different API or rewrite the implement PR.

Taco intent: presence is a **humanoid of thousands of glowing orbs**; morphable; expandable shape catalog.

### Shape catalog

Source of truth: `frontend/src/presence/renderers/shapes/catalog.ts` (types in `particleTypes.ts`).

- `PresenceShapeId` — string ids.
- `PresenceShapeDefinition`: `{ id, label, buildFigure(density), buildField?(density), framing? }`
  - `buildFigure` returns figure orbs that morph between shapes.
  - `buildField` is an optional environment layer (mountains / HUD dust).
  - `framing` is optional `{ yaw?, position? }` (¾ profile bust ≈ yaw `0.95`).
- Registry: `registerPresenceShape`, `listPresenceShapes`, `resolvePresenceShape`, `presenceShapeIdForAvatar`.
- Default: `humanoid_bust` (`DEFAULT_PRESENCE_SHAPE_ID`).
- Built-ins registered at load:
  - `humanoid_bust` — ref-parity orb bust + optional field (`shapes/humanoidBust.ts`).
  - `energy_core` — expandable stub proving a second registered shape (`shapes/energyCore.ts`).
- Persisted `PresentationSettings.avatarId` maps to shape id via `presenceShapeIdForAvatar`:
  - `jarvis_base` or empty → default `humanoid_bust`.
  - Direct registered id, or `shape:<id>`.
  - Unknown avatars fall back to the default bust.
- Catalog is intentionally expandable via `registerPresenceShape` without forking `PresenceHost`.

### Morph API

Source of truth: `frontend/src/presence/renderers/morphableOrbCloud.ts` + `particleTypes.ts`.

- Fixed-budget orb cloud with A/B attribute slots (`aPos`/`bPos`, sizes, gold, light, flow) and shader uniform `uMorph` (0..1 lerp).
- Morph between registered shapes **without remounting** the humanoid presence renderer (`HumanoidPresence` optional `shapeId` override; avatarId/shapeId morph inside the frame loop).
- Soft glowing orb points (not mesh). Reduced-motion / performance presets continue to apply per RFC-0051 (reduced motion snaps morph immediately; efficient/cinematic density still applies).
- Environment `buildField` layers may swap (not necessarily morph-lerped).
- Decorative canvas: screen-reader state on the host; canvas remains non-essential (RFC-0051). No camera acquisition.

### Ground truth

Owner reference reel / photos. `humanoid_bust` is the visual default (thousands of glowing orbs). No third-party or licensed character assets.

**Will not:** rewrite Classic/Neural shells; camera/biometrics; require paid avatar packs; specify every future shape’s geometry here (only the catalog + morph contract and the first shapes).

## Acceptance criteria

- [x] RFC documents catalog + morph contract matching #166 names above
- [x] `humanoid_bust` first; catalog expandable (`energy_core` as proof stub ok)
- [x] `avatarId` → shape id mapping documented
- [x] Reduced-motion / no-camera / decorative-canvas constraints referenced from RFC-0051
- [x] Specs-only PR (no product code)

## Likely files

For implementers — already largely in #166:

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/presence/renderers/shapes/catalog.ts`, `shapes/humanoidBust.ts`, `shapes/energyCore.ts`, `morphableOrbCloud.ts`, `particleTypes.ts`, `HumanoidPresence.tsx`, `frontend/presence-check.tsx` |
| Docs | this RFC; optional §59 Decision Log line |

## Out of scope

- Rewriting Classic/Neural shells or PresenceHost selection (RFC-0050).
- Camera attention, biometrics, or MediaStream (RFC-0050 / RFC-0051).
- Paid / licensed avatar packs (RFC-0052 entitlements).
- Per-shape geometry beyond `humanoid_bust` + `energy_core`.
- Product/frontend/backend changes in this PR.

## Notes

Cite #165 as the visual-parity baseline and #166 as the morph-catalog implement PR. Implementation may land after or with this RFC; this RFC is the ledger for Watch % and CoS land order (specs first, then #166, without renaming the shipped surface).

## Implementation note

Landed on `development` via #168 (specs) + #166 (impl @ `4e7b97d`). Surface: `shapes/catalog.ts`, `humanoidBust` + `energyCore`, `morphableOrbCloud`/`uMorph`.
