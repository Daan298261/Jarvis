import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { makeRng, pushOrb, ring } from "./figureKit"

/** Umi's distinct indigo reasoning tide. It is not Nabu's rings or Aegir's media swell. */
export function buildOpusTideFigure(density: number): ParticleOrb[] {
  const random = makeRng(19514)
  const orbs: ParticleOrb[] = []
  const bands = 15
  for (let band = 0; band < bands; band++) {
    const y = -1.22 + band * 0.17
    const count = Math.max(80, Math.round(420 * density))
    for (let i = 0; i < count; i++) {
      const u = i / Math.max(1, count - 1)
      const x = (u * 2 - 1) * (1.42 - Math.abs(y) * 0.18)
      const phase = x * 3.2 + band * 0.62
      pushOrb(
        orbs,
        x,
        y + Math.sin(phase) * (0.08 + band * 0.004),
        Math.cos(phase * 0.72) * 0.24 + (random() - 0.5) * 0.05,
        band % 5 === 0 ? 0.72 : 0.04,
        0.8 + random() * 0.9,
        0.46,
        1.05 + random() * 0.7,
        density,
      )
    }
  }
  for (let layer = 0; layer < 5; layer++) {
    ring(orbs, random, Math.max(120, Math.round(620 * density)), 0.34 + layer * 0.12,
      0.22, layer === 2 ? 0.9 : 0.12, 1.1, 0.38, 1.2, density, (layer - 2) * 0.16)
  }
  return orbs
}

export const opusTideShape: PresenceShapeDefinition = {
  id: "opus_tide",
  label: "Opus tide",
  buildFigure: buildOpusTideFigure,
  framing: { yaw: 0, position: [0, -0.02, 0], fitMargin: 0.88 },
  appearance: { pointScale: 0.94, depthSoftness: 0.08, glow: 0.82, bloomStrength: 0.24 },
}
