import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb } from "./figureKit"

/** Yellow/cyan comet-orb with twin trails and rapid particles. */
export function buildCometTrailFigure(density: number): ParticleOrb[] {
  const random = makeRng(9129)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(1400 * density), 0.42, 0.2, 0.9, 1.7, 0, 1.6, density)
  for (const spread of [-0.16, 0.16]) {
    const steps = Math.round(280 * density)
    for (let i = 0; i < steps; i++) {
      const t = i / steps
      pushOrb(
        orbs,
        0.15 - t * 1.35,
        0.2 + spread * (1 - t),
        -t * 0.35,
        t < 0.25 ? 1 : 0.15,
        1.5 - t * 0.6,
        0.58,
        1.4 - t * 0.4,
        density,
      )
    }
  }
  const rapid = Math.round(220 * density)
  for (let i = 0; i < rapid; i++) {
    const a = random() * Math.PI * 2
    const r = 0.55 + random() * 0.5
    pushOrb(orbs, Math.cos(a) * r, 0.2 + Math.sin(a * 2) * 0.2, Math.sin(a) * r * 0.6, 0.4, 1.2, 0.6, 1.05, density)
  }
  return orbs
}

export const cometTrailShape: PresenceShapeDefinition = {
  id: "comet_trail",
  label: "Comet trail",
  buildFigure: buildCometTrailFigure,
  framing: { yaw: -0.35, position: [0.1, 0.05, 0] },
}
