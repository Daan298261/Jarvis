import type { AttentionMode, PresenceMode, PresencePhase } from "./presenceTypes"

/** RFC-0069 duration. Non-reduced free↔figure morph. Reduced motion snaps. */
export const LIFECYCLE_MORPH_SECONDS = 1.2

const IDLE_PHASES = new Set<PresencePhase>(["idle", "waiting", "offline"])

export function isIdlePresencePhase(phase: PresencePhase): boolean {
  return IDLE_PHASES.has(phase)
}

/** 0 = free-float cloud (Ref A). 1 = winning figure (Ref B, or the shape that won precedence). */
export function lifecycleMorphTarget(phase: PresencePhase): 0 | 1 {
  return isIdlePresencePhase(phase) ? 0 : 1
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
