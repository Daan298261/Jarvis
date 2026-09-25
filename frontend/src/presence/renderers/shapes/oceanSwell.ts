import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb, ring } from "./figureKit"

/** Teal liquid orb, wave ripples, lens flares, flowing signal trails. */
export function buildOceanSwellFigure(density: number): ParticleOrb[] {
  const random = makeRng(7907)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(2200 * density), 0.7, 0.06, 0.25, 1.2, 0, 1.5, density, 0.86)
  for (let band = 1; band <= 4; band++) {
    ring(
      orbs,
      random,
      Math.round(160 * density),
      0.4 + band * 0.18,
      0.02 + Math.sin(band) * 0.04,
      band === 4 ? 1 : 0.1,
      1.15,
      0.4,
      1.2,
      density,
      0.05,
    )
  }
  const trail = Math.round(140 * density)
  for (let i = 0; i < trail; i++) {
    const t = i / trail
    pushOrb(orbs, -0.2 + t * 1.3, 0.35 - t * 0.5, -0.1 - t * 0.4, 0.8, 1.6, 0.62, 1.2, density)
  }
  return orbs
}

export const oceanSwellShape: PresenceShapeDefinition = {
  id: "ocean_swell",
  label: "Ocean swell",
  buildFigure: buildOceanSwellFigure,
  framing: { yaw: 0.1, position: [0, 0.06, 0] },
}
