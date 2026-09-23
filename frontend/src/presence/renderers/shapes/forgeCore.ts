import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb, ring } from "./figureKit"

/** Orange/red molten core, sparks, forge rings, heat shimmer. */
export function buildForgeCoreFigure(density: number): ParticleOrb[] {
  const random = makeRng(13513)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(2200 * density), 0.58, 0.08, 0.95, 1.7, 0, 1.55, density)
  ring(orbs, random, Math.round(220 * density), 0.82, 0.02, 1, 1.4, 0.4, 1.3, density, 0.25)
  ring(orbs, random, Math.round(180 * density), 0.98, 0.2, 0.4, 1.25, 0.4, 1.2, density, -0.2)
  const sparks = Math.round(260 * density)
  for (let i = 0; i < sparks; i++) {
    const a = random() * Math.PI * 2
    const r = 0.6 + random() * 0.55
    pushOrb(orbs, Math.cos(a) * r, 0.1 + random() * 0.7, Math.sin(a) * r * 0.5, 1, 2, 1.15, 1.05, density)
  }
  return orbs
}

export const forgeCoreShape: PresenceShapeDefinition = {
  id: "forge_core",
  label: "Forge core",
  buildFigure: buildForgeCoreFigure,
  framing: { yaw: 0.12, position: [0, 0.06, 0] },
}
