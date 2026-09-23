import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { makeRng, pushOrb, ring } from "./figureKit"

/** Coral/pink star-orb, orbiting social nodes, expanding signal rings. */
export function buildStarSocialFigure(density: number): ParticleOrb[] {
  const random = makeRng(12412)
  const orbs: ParticleOrb[] = []
  const count = Math.round(2000 * density)
  for (let i = 0; i < count; i++) {
    const a = random() * Math.PI * 2
    const b = Math.acos(random() * 2 - 1)
    const spikes = 0.72 + 0.28 * Math.pow(Math.abs(Math.cos(a * 2.5) * Math.sin(b * 2.5)), 0.45)
    const shell = Math.pow(random(), 0.5) * spikes
    pushOrb(
      orbs,
      Math.sin(b) * Math.cos(a) * shell,
      Math.sin(b) * Math.sin(a) * shell * 0.9 + 0.1,
      Math.cos(b) * shell,
      shell > 0.7 ? 1 : 0.2,
      1.35,
      shell < 0.25 ? 2 : 0,
      1.4,
      density,
    )
  }
  for (let n = 0; n < 6; n++) {
    const a = (n / 6) * Math.PI * 2
    pushOrb(orbs, Math.cos(a) * 0.95, 0.1 + Math.sin(a) * 0.15, Math.sin(a) * 0.7, 1, 2.1, 0.52, 2.4, density)
  }
  ring(orbs, random, Math.round(180 * density), 1.05, 0.1, 0.3, 1.2, 0.42, 1.15, density)
  ring(orbs, random, Math.round(140 * density), 1.22, 0.1, 0.9, 1.15, 0.42, 1.1, density)
  return orbs
}

export const starSocialShape: PresenceShapeDefinition = {
  id: "star_social",
  label: "Star social",
  buildFigure: buildStarSocialFigure,
  framing: { yaw: 0.18, position: [0, 0.06, 0] },
}
