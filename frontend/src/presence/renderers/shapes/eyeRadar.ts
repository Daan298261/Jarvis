import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { makeRng, pushOrb, ring } from "./figureKit"

/** Orange/blue eye-shaped orb, scanning rings, radar sweep. */
export function buildEyeRadarFigure(density: number): ParticleOrb[] {
  const random = makeRng(10210)
  const orbs: ParticleOrb[] = []
  const count = Math.round(2200 * density)
  for (let i = 0; i < count; i++) {
    const a = random() * Math.PI * 2
    const b = Math.acos(random() * 2 - 1)
    const shell = Math.pow(random(), 0.5)
    const r = shell * 0.62
    pushOrb(
      orbs,
      Math.sin(b) * Math.cos(a) * r * 1.35,
      Math.sin(b) * Math.sin(a) * r * 0.72 + 0.1,
      Math.cos(b) * r,
      shell < 0.3 ? 1 : 0.1,
      1.3,
      shell < 0.2 ? 2 : 0,
      1.35,
      density,
    )
  }
  ring(orbs, random, Math.round(200 * density), 0.9, 0.1, 0.8, 1.4, 0.4, 1.2, density)
  ring(orbs, random, Math.round(160 * density), 1.1, 0.1, 0.2, 1.2, 0.4, 1.15, density)
  const sweep = Math.round(90 * density)
  for (let i = 0; i < sweep; i++) {
    const t = i / sweep
    pushOrb(orbs, Math.cos(0.6) * t * 1.15, 0.1, Math.sin(0.6) * t * 1.15, 1, 1.8, 0.47, 1.25, density)
  }
  return orbs
}

export const eyeRadarShape: PresenceShapeDefinition = {
  id: "eye_radar",
  label: "Eye radar",
  buildFigure: buildEyeRadarFigure,
  framing: { yaw: 0, position: [0, 0.06, 0] },
}
