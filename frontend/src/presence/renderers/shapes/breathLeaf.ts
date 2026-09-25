import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb } from "./figureKit"

/** Soft mint/rose orb, leaf motifs, smooth breathing shell. */
export function buildBreathLeafFigure(density: number): ParticleOrb[] {
  const random = makeRng(11311)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(2000 * density), 0.66, 0.08, 0.35, 1.05, 0.15, 1.45, density, 0.95)
  for (const side of [-1, 1]) {
    const steps = Math.round(180 * density)
    for (let i = 0; i < steps; i++) {
      const t = i / steps
      const leaf = Math.sin(t * Math.PI)
      pushOrb(
        orbs,
        side * (0.15 + leaf * 0.55),
        0.15 + (t - 0.5) * 0.7,
        leaf * 0.08,
        0.7,
        1.2,
        0.32,
        1.3,
        density,
      )
    }
  }
  return orbs
}

export const breathLeafShape: PresenceShapeDefinition = {
  id: "breath_leaf",
  label: "Breath leaf",
  buildFigure: buildBreathLeafFigure,
  framing: { yaw: 0.05, position: [0, 0.06, 0] },
}
