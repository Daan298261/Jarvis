import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb, ring } from "./figureKit"

/** Ice-blue orb, two shield halos, central status line. */
export function buildTwinShieldFigure(density: number): ParticleOrb[] {
  const random = makeRng(6806)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(1800 * density), 0.5, 0.1, 0.9, 1.4, 0, 1.4, density)
  ring(orbs, random, Math.round(260 * density), 0.78, 0.22, 1, 1.5, 0.4, 1.3, density, 0.9)
  ring(orbs, random, Math.round(260 * density), 0.78, -0.02, 0.2, 1.45, 0.4, 1.3, density, -0.9)
  const line = Math.round(80 * density)
  for (let i = 0; i < line; i++) {
    const t = i / line
    pushOrb(orbs, -0.55 + t * 1.1, 0.1, 0.05, 1, 1.7, 0.36, 1.15, density)
  }
  return orbs
}

export const twinShieldShape: PresenceShapeDefinition = {
  id: "twin_shield",
  label: "Twin shield",
  buildFigure: buildTwinShieldFigure,
  framing: { yaw: 0.05, position: [0, 0.08, 0] },
}
