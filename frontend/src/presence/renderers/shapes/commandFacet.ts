import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb, ring } from "./figureKit"

function hexRing(orbs: ParticleOrb[], density: number, radius: number, y: number): void {
  const edge = Math.round(70 * density)
  for (let i = 0; i < 6; i++) {
    const a0 = (Math.PI / 3) * i
    const a1 = (Math.PI / 3) * (i + 1)
    for (let s = 0; s < edge; s++) {
      const t = s / edge
      const ang = a0 + (a1 - a0) * t
      const x = Math.cos(ang) * radius
      const z = Math.sin(ang) * radius
      pushOrb(orbs, x, y, z, 1, 1.5, 0.42, 1.3, density)
    }
  }
}

/** Blue-white faceted command orb with rotating hexagonal rings. */
export function buildCommandFacetFigure(density: number): ParticleOrb[] {
  const random = makeRng(2402)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(2200 * density), 0.62, 0.1, 0.85, 1.2, 0, 1.4, density, 1)
  hexRing(orbs, density, 0.85, 0.1)
  hexRing(orbs, density, 1.05, 0.28)
  ring(orbs, random, Math.round(180 * density), 0.95, -0.05, 0.4, 1.1, 0.42, 1.2, density, 0.4)
  return orbs
}

export const commandFacetShape: PresenceShapeDefinition = {
  id: "command_facet",
  label: "Command facet",
  buildFigure: buildCommandFacetFigure,
  framing: { yaw: 0.2, position: [0, 0.08, 0] },
}
