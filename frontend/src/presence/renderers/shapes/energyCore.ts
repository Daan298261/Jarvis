import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"

/** Compact morph target — proves catalog expansion; not the visual parity default. */
export function buildEnergyCoreFigure(density: number): ParticleOrb[] {
  let seed = 2201
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  const orbs: ParticleOrb[] = []
  const count = Math.round(9000 * density)
  for (let i = 0; i < count; i++) {
    const a = random() * Math.PI * 2
    const b = Math.acos(random() * 2 - 1)
    const shell = Math.pow(random(), 0.55)
    const r = shell * 0.85
    const x = Math.sin(b) * Math.cos(a) * r
    const y = Math.sin(b) * Math.sin(a) * r * 0.9
    const z = Math.cos(b) * r
    const gold = shell < 0.35 ? 1 : 0
    orbs.push({
      x, y: y + 0.15, z,
      gold,
      light: gold ? 1.6 + (1 - shell) * 1.2 : 0.35 + (1 - shell) * 1.4,
      flow: shell > 0.75 ? 0.35 : shell < 0.2 ? 2 : 0,
      size: (gold ? 1.7 : 1.35 + random() * 0.5) / Math.sqrt(density),
    })
  }
  orbs.push({ x: 0, y: 0.15, z: 0, gold: 0, light: 0.8, flow: 2, size: 70 / Math.sqrt(density) })
  return orbs
}

export const energyCoreShape: PresenceShapeDefinition = {
  id: "energy_core",
  label: "Energy core",
  buildFigure: buildEnergyCoreFigure,
  framing: { yaw: 0.2, position: [0, 0.1, 0] },
}
