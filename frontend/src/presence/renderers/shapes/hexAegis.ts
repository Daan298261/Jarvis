import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"

/** Pointy-top hexagon vertex in XZ, Y unused. */
function hexVertex(index: number, radius: number, yScale = 1): { x: number; y: number; z: number } {
  const angle = (Math.PI / 3) * index - Math.PI / 6
  return {
    x: Math.cos(angle) * radius,
    y: 0,
    z: Math.sin(angle) * radius * yScale,
  }
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

/** Hexagonal aegis — nested lattice + shield core for the HexStrike suite. */
export function buildHexAegisFigure(density: number): ParticleOrb[] {
  let seed = 7781
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  const orbs: ParticleOrb[] = []
  const emit = (
    x: number, y: number, z: number,
    gold: number, light: number, flow = 0, size = 1.5,
  ) => {
    orbs.push({ x, y, z, gold, light, flow, size: size / Math.sqrt(density) })
  }

  const rings = Math.round(7 * density)
  for (let ring = 1; ring <= rings; ring++) {
    const radius = (ring / rings) * 1.05
    const edge = Math.max(28, Math.round(52 * density * (0.45 + radius)))
    const inner = ring / rings
    for (let i = 0; i < 6; i++) {
      const a = hexVertex(i, radius, 0.92)
      const b = hexVertex(i + 1, radius, 0.92)
      for (let s = 0; s < edge; s++) {
        const t = s / edge
        const x = lerp(a.x, b.x, t)
        const z = lerp(a.z, b.z, t)
        const jitter = (random() - 0.5) * 0.012
        const gold = inner < 0.38 || ring === rings ? 1 : inner > 0.78 ? 0.35 : 0
        const light = gold ? 1.7 + (1 - inner) * 1.4 : 0.45 + inner * 1.5
        emit(x + jitter, 0.22 + Math.sin(inner * 4) * 0.04, z + jitter, gold, light, inner > 0.85 ? 0.4 : 0, 1.45 + random() * 0.4)
      }
    }
  }

  const fill = Math.round(4200 * density)
  for (let i = 0; i < fill; i++) {
    const u = random() * 2 - 1
    const v = random() * 2 - 1
    const q = u
    const r = v
    const s = -q - r
    const hexDist = (Math.abs(q) + Math.abs(r) + Math.abs(s)) / 2
    if (hexDist > 0.92) continue
    const x = (q + r / 2) * 1.12
    const z = (r * Math.sqrt(3) / 2) * 1.02
    const gold = hexDist < 0.22 ? 1 : hexDist < 0.45 && random() < 0.35 ? 0.8 : 0
    emit(
      x + (random() - 0.5) * 0.02,
      0.2 + (0.22 - hexDist) * 0.18,
      z,
      gold,
      gold ? 1.8 + (1 - hexDist) * 1.6 : 0.28 + (1 - hexDist) * 1.1,
      hexDist < 0.18 ? 2 : 0,
      gold ? 1.7 : 1.2 + random() * 0.4,
    )
  }

  for (let spoke = 0; spoke < 6; spoke++) {
    const tip = hexVertex(spoke, 1.02, 0.92)
    const count = Math.round(90 * density)
    for (let i = 0; i < count; i++) {
      const t = i / count
      emit(tip.x * t, 0.22, tip.z * t, t > 0.7 ? 1 : 0, 0.7 + t * 1.8, 0, 1.25)
    }
  }

  emit(0, 0.24, 0, 0, 1.1, 2, 78 / Math.sqrt(density))
  return orbs
}

export function buildHexAegisField(density: number): ParticleOrb[] {
  let seed = 4409
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  const orbs: ParticleOrb[] = []
  const emit = (
    x: number, y: number, z: number,
    gold: number, light: number, flow = 1, size = 1.1,
  ) => {
    orbs.push({ x, y, z, gold, light, flow, size: size / Math.sqrt(density) })
  }
  const cells = Math.round(18 * density)
  for (let row = -cells; row <= cells; row++) {
    for (let col = -cells; col <= cells; col++) {
      const x = (col + (row & 1) * 0.5) * 0.42
      const y = row * 0.36
      if (Math.hypot(x, y) > 3.4) continue
      if (random() < 0.35) continue
      emit(x, y * 0.55, -1.45 - random() * 0.4, random() < 0.12 ? 0.9 : 0, 0.08 + random() * 0.22, 1, 0.95)
    }
  }
  return orbs
}

export const hexAegisShape: PresenceShapeDefinition = {
  id: "hex_aegis",
  label: "Hex aegis",
  buildFigure: buildHexAegisFigure,
  buildField: buildHexAegisField,
  framing: { yaw: 0.12, position: [0, 0.08, 0] },
}
