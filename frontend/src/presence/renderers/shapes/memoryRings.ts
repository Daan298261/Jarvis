import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb, ring } from "./figureKit"

/** Amber/indigo orb, layered memory rings, floating glyph ticks. */
export function buildMemoryRingsFigure(density: number): ParticleOrb[] {
  const random = makeRng(3503)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(2000 * density), 0.58, 0.08, 0.7, 1.25, 0, 1.4, density)
  for (let band = 0; band < 4; band++) {
    ring(
      orbs,
      random,
      Math.round(200 * density),
      0.72 + band * 0.14,
      0.02 + band * 0.08,
      band % 2 === 0 ? 1 : 0.15,
      1.3,
      0.38,
      1.25,
      density,
      band * 0.18,
    )
  }
  const glyphs = Math.round(80 * density)
  for (let i = 0; i < glyphs; i++) {
    const x = (random() - 0.5) * 1.6
    const y = 0.2 + random() * 0.9
    const z = (random() - 0.5) * 0.4
    for (let s = 0; s < 4; s++) {
      pushOrb(orbs, x, y + s * 0.03, z, 0.2, 1.6, 0.45, 1.05, density)
    }
  }
  return orbs
}

export const memoryRingsShape: PresenceShapeDefinition = {
  id: "memory_rings",
  label: "Memory rings",
  buildFigure: buildMemoryRingsFigure,
  framing: { yaw: 0.12, position: [0, 0.08, 0] },
}
