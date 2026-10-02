# RFC-0051 — Humanoid Presence Runtime

Status: Implemented

**Amended:** 2026-09-30 — [RFC-0195](0195-visual-acceptance-and-presence-stage.md) strengthens silhouette, camera look-at, depth, and bloom acceptance. Status stays **Implemented** for the original land. New visual rows stay **unchecked** until Desktop soak. This amend does **not** reopen camera capture inside the humanoid runtime.

Priority: P0 / Owner priority

Target: Jarvis desktop frontend

Depends on: RFC-0050 presence architecture, RFC-0060 docs-first grounding

Related: RFC-0058 APEX feature parity, RFC-0061 chat-to-TTS

## Problem

RFC-0050 made `humanoid` a persisted presentation choice but intentionally left it unavailable. The current Neural HUD is also visually undersized on normal desktop displays, and the reference pack does not explain how to activate or troubleshoot the humanoid runtime.

## Decision

Ship an original, local, lazy-loaded humanoid renderer behind the existing `PresenceHost`. The base avatar is procedurally constructed from Jarvis-owned geometry, so it does not require a third-party character asset, account, or separate download. The renderer consumes only the canonical presence snapshot and presentation settings.

Complete the presence experience with two narrow integrations:

1. Increase the Neural HUD desktop scale while keeping responsive/mobile bounds.
2. Publish humanoid setup and troubleshooting guidance into the RFC-0060 reference pack at `project/jarvis/jarvis/internal/references/`, so self-help questions use the existing docs-first grounding pipeline.

## Amend (2026-09-30) — silhouette / camera / depth / bloom

**This amend overrides** the undersized-Neural reading that a 920px / 680∶480 capped box counted as “materially larger.” **RFC-0195** is the stage contract: the shared WebGL presence **fills the available presence viewport**. HUD chrome overlays; it does not steal avatar space. Crop-protection (AABB + geometric center) stays RFC-0194 Decision 2.

**Readable silhouette first:**

- Camera look-at uses shape **landmarks** (RFC-0069 amend) + geometric center, not origin-symmetric fit.
- Depth softness (RFC-0176) must not erase landmark edges.
- Bloom / emission / particle alpha must keep a stranger able to name the persona from a rest still. An overexposed slab at high FPS is a **fail**.
- Idle rest is a humanoid / winning-figure silhouette (RFC-0195). The humanoid runtime must not hide the figure at `idle`.

**Unchanged:** the runtime never opens the camera; pointer attention only when enabled; lazy load; fallback humanoid → neural → static; reduced motion; decorative canvas.

### Added acceptance (unchecked — Desktop soak)

- [ ] Presence canvas fills the HUD presence viewport (no primary 920×680∶480 stage).
- [ ] Rest phase keeps a readable humanoid / winning-figure silhouette; bloom does not wash identity (Mestor slab = fail).
- [ ] Look-at / depth use landmarks + AABB center; origin-symmetric crush stays forbidden.

## Humanoid renderer contract

- Lazy loaded only when `requestedPresence === "humanoid"`.
- Uses the existing `PresenceSnapshot` phases: idle, listening, thinking, executing, speaking, waiting, alert, and offline.
- Uses pointer attention only when enabled. It never opens the camera.
- Respects efficient/cinematic presets and reduced-motion settings.
- Stops useful rendering work while the page is hidden.
- Disposes WebGL resources and event listeners on unmount.
- Falls back in order: humanoid -> neural -> static.
- Exposes concise screen-reader state; the canvas is decorative.

## Acceptance criteria

- [ ] Humanoid HUD hot-switches without a restart or conversation loss.
- [ ] The humanoid is a lazy frontend chunk and does not load in Classic/Neural modes.
- [ ] All canonical phases cause truthful, distinct avatar behavior.
- [ ] Pointer attention, reduced motion, visibility pause, cleanup, and performance presets work.
- [ ] A renderer/WebGL failure leaves chat usable through Neural/static fallback.
- [ ] Neural presence is materially larger on normal desktop displays and remains responsive. **RFC-0195:** “larger” means **viewport-fill**, not a 920px / 680∶480 postage stamp.
- [ ] Humanoid setup guidance is indexed by the RFC-0060 docs-first pipeline.
- [ ] Frontend lint/build and focused backend tests pass.

## Likely files

- `frontend/src/presence/PresenceHost.tsx`
- `frontend/src/presence/renderers/HumanoidPresence.tsx`
- `frontend/src/presence/renderers/humanoid-presence.css`
- `project/jarvis/jarvis/internal/references/humanoid-runtime.md`

## Out of scope

- Camera capture, face recognition, or biometric data.
- Actor/character voice cloning.
- Model tone/personality prompt changes.
- Typed-chat speech and persona behavior (owned by RFC-0061).
- Internal-reference retrieval and prompt integration (owned by RFC-0060).
- Premium entitlements or paid avatar packs.
- A full RFC-0056 expressive-TTS provider benchmark.
