import type { AttentionMode, PresenceMode, PresencePhase } from "./presenceTypes"

/** RFC-0069 duration. Non-reduced rest↔figure morph. Reduced motion snaps. */
export const LIFECYCLE_MORPH_SECONDS = 1.2

/**
 * RFC-0195 Decision 1 — rest tightness, locked in [0.72, 0.92].
 * Idle / waiting / offline keep a recognizably humanoid (or winning-figure)
 * silhouette. They must not target `uMorph` 0 (void RFC-0194 idle identity-hide).
 */
export const REST_TIGHTNESS = 0.82

/** Engaged phases (thinking, listening, speaking, executing, alert, error, approval). */
export const ENGAGED_TIGHTNESS = 1

export const REST_TIGHTNESS_MIN = 0.72
export const REST_TIGHTNESS_MAX = 0.92

/** Historical name: rest phases. Not a free-float identity-hide. */
const REST_PHASES = new Set<PresencePhase>(["idle", "waiting", "offline"])

export function isRestPresencePhase(phase: PresencePhase): boolean {
  return REST_PHASES.has(phase)
}

/** @deprecated RFC-0195 — alias of {@link isRestPresencePhase}. Rest is not a void cloud. */
export function isFreePresencePhase(phase: PresencePhase): boolean {
  return isRestPresencePhase(phase)
}

export function clampLifecycleMorph(value: number): number {
  if (!Number.isFinite(value)) return REST_TIGHTNESS
  if (value <= 0) return REST_TIGHTNESS
  return Math.max(0, Math.min(ENGAGED_TIGHTNESS, value))
}

/**
 * Rest → {@link REST_TIGHTNESS}. Engaged → {@link ENGAGED_TIGHTNESS}.
 * Never returns 0: that was the RFC-0194 identity-hide contract, now void.
 */
export function lifecycleMorphTarget(phase: PresencePhase): number {
  return isRestPresencePhase(phase) ? REST_TIGHTNESS : ENGAGED_TIGHTNESS
}

/**
 * Free→figure runs for every mounted presence avatar.
 * `none` (Classic with no avatar) does not grow a canvas.
 * Galaxy is not the gate.
 */
export function presenceLifecycleEnabled(mode: PresenceMode): boolean {
  return mode !== "none"
}

export type PresenceAttract = {
  chase: boolean
  source: "pointer" | "camera" | "hold"
  x: number
  y: number
}

/**
 * Idle attract.
 * Face samples apply only when camera attention is already on and the tracker
 * returned confidence above zero. Missing, denied, or failed tracking stays on
 * the pointer. `off` and reduced motion hold the cloud and do not chase.
 * Attract may bias rest; it must not drive rest to an anonymous free cloud.
 */
export function resolvePresenceAttract(input: {
  attentionMode: AttentionMode
  reduced: boolean
  pointerX: number
  pointerY: number
  cameraX: number
  cameraY: number
  cameraConfidence: number
  cameraAvailable: boolean
}): PresenceAttract {
  if (input.reduced || input.attentionMode === "off") {
    return { chase: false, source: "hold", x: 0, y: 0 }
  }
  if (
    input.attentionMode === "camera"
    && input.cameraAvailable
    && input.cameraConfidence > 0
  ) {
    return {
      chase: true,
      source: "camera",
      x: input.cameraX,
      y: input.cameraY,
    }
  }
  return {
    chase: true,
    source: "pointer",
    x: input.pointerX,
    y: input.pointerY,
  }
}
