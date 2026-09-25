import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb } from "./figureKit"

/** Large red-gold storm orb, wing arcs, slow electrical pulses. */
export function buildStormbirdFigure(density: number): ParticleOrb[] {
  const random = makeRng(1301)
  const orbs: ParticleOrb[] = []
  const count = Math.round(2800 * density)
  fillSphere(orbs, random, count, 0.78, 0.12, 0.15, 1.35, 0, 1.5, density)
  const arc = Math.round(420 * density)
  for (const side of [-1, 1]) {
    for (let i = 0; i < arc; i++) {
      const t = i / arc
      const ang = -0.4 + t * 2.5
      const reach = 0.35 + Math.sin(t * Math.PI) * 0.95
      pushOrb(
        orbs,
        side * Math.cos(ang) * reach,
        0.2 + Math.sin(ang) * 0.42,
        Math.sin(t * 6) * 0.08,
        t > 0.55 ? 1 : 0.2,
        1.4,
        0.4,
        1.35,
        density,
      )
    }
  }
  const sparks = Math.round(180 * density)
  for (let i = 0; i < sparks; i++) {
    const side = i % 2 === 0 ? -1 : 1
    pushOrb(
      orbs,
      side * (0.2 + random() * 1.1),
      0.05 + random() * 0.7,
      (random() - 0.5) * 0.2,
      1,
      2.2,
      2,
      1.1,
      density,
    )
  }
  return orbs
}

export const stormbirdShape: PresenceShapeDefinition = {
  id: "stormbird",
  label: "Stormbird",
  buildFigure: buildStormbirdFigure,
  framing: { yaw: 0.08, position: [0, 0.06, 0] },
}
