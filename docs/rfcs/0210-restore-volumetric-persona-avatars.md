# RFC-0210: Restore detailed live persona avatars

**Status:** accepted
**Author:** Codex
**Date:** 2026-10-09

## Problem

Persona activation selects `mythic_live_b`, introduced in #527, which bypasses the detailed persona artwork and draws procedural masks. #533 further replaced the bird and owl with outline strokes. The brightness/detail controls added in #541 are absent from the HUD Appearance menu, and opening that menu replaces the avatar with a settings cloud so adjustments cannot be judged.

## Decision

Restore the original artwork in both A and B. B uses a closed particle relief with curved front, side and rear samples, pointer/optional-camera gaze, breathing and gentle hovering through the existing shared stage. This is a depth reconstruction from the supplied artwork, not a rigged mesh or an invented unseen anatomical model. Keep both humanoid paths intact. Expose persistent brightness and density sliders in the HUD Appearance menu and retain the avatar while adjusting it. Guard appearance responses against stale saves.

## Acceptance criteria

- All fourteen named personas use their detailed artwork in B, with measurable depth and a rear surface; A remains available.
- Humanoid artwork and terrain remain unchanged.
- Live gaze and idle motion respect reduced motion and animation intensity.
- Brightness and density are immediately visible, persistent, and previewable in Appearance.
- Rapid A/B changes cannot be undone by older settings responses.
- Geometry/selection regression tests, frontend build/lint and pytest pass.
- Verify all persona artwork in the browser harness; record installed-artifact limits separately.

## Likely files

Shared portrait builder, HumanoidPresence, MorphablePresenceStage, presentationSettings, persona appearance controls, HUD, browser harness and tests.

## Out of scope

Installer packaging, model/voice changes and humanoid redesign.
