import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb } from "./figureKit"

/** Dark violet/green orb, serpent orbit, intermittent shadow fractures. */
export function buildSerpentOrbitFigure(density: number): ParticleOrb[] {
  const random = makeRng(5705)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(2000 * density), 0.6, 0.08, 0.05, 0.9, 0, 1.35, density)
  const steps = Math.round(520 * density)
  for (let i = 0; i < steps; i++) {
    const t = (i / steps) * Math.PI * 2
    const lift = Math.sin(t * 3) * 0.28
    pushOrb(
      orbs,
      Math.cos(t) * (0.85 + lift * 0.2),
      0.1 + lift,
      Math.sin(t) * 0.72,
      i % 7 === 0 ? 1 : 0.1,
      1.3,
      0.5,
      1.25,
      density,
    )
  }
  for (let f = 0; f < 3; f++) {
    const y = -0.15 + f * 0.22
    for (let s = 0; s < Math.round(40 * density); s++) {
      pushOrb(orbs, -0.2 + s * 0.012, y + (s % 5) * 0.01, 0.15, 0, 0.55, 0.55, 1.1, density)
    }
  }
  return orbs
}

export const serpentOrbitShape: PresenceShapeDefinition = {
  id: "serpent_orbit",
  label: "Serpent orbit",
  buildFigure: buildSerpentOrbitFigure,
  framing: { yaw: 0.15, position: [0, 0.08, 0] },
}
