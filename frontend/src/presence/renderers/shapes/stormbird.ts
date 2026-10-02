import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { makeRng, pushOrb } from "./figureKit"

/** Anzu's storm-bird head: frontal eagle mask, hooked beak and lightning crown. */
export function buildStormbirdFigure(density: number): ParticleOrb[] {
  const random = makeRng(1301)
  const orbs: ParticleOrb[] = []
  const emitStroke = (points: Array<[number, number]>, count: number, gold = 0.08, light = 1.5) => {
    for (let i = 0; i < Math.round(count * density); i++) {
      const u = i / Math.max(1, Math.round(count * density) - 1)
      const segment = Math.min(points.length - 2, Math.floor(u * (points.length - 1)))
      const local = u * (points.length - 1) - segment
      const a = points[segment], b = points[segment + 1]
      pushOrb(orbs,
        a[0] + (b[0] - a[0]) * local + (random() - 0.5) * 0.018,
        a[1] + (b[1] - a[1]) * local + (random() - 0.5) * 0.018,
        (random() - 0.5) * 0.18, gold, light + random() * 0.8, 0.35, 1.35, density)
    }
  }

  // Symmetric skull silhouette reads as a head instead of a sphere or hand.
  for (const side of [-1, 1]) {
    emitStroke([[0, 1.36], [side * 0.42, 1.22], [side * 0.76, 0.84], [side * 0.88, 0.34], [side * 0.68, -0.24], [side * 0.38, -0.78], [0, -1.28]], 1350, 0.06, 1.5)
    emitStroke([[side * 0.12, 0.92], [side * 0.48, 0.78], [side * 0.7, 0.46], [side * 0.34, 0.5], [side * 0.08, 0.4]], 520, 0.22, 1.4)
  }
  // Swept storm-feather crown and cheek wings.
  for (const side of [-1, 1]) {
    for (let feather = 0; feather < 9; feather++) {
      const rootX = side * (0.08 + feather * 0.07)
      emitStroke([[rootX, 1.02 - feather * 0.025], [side * (0.34 + feather * 0.12), 1.3 + feather * 0.035], [side * (0.58 + feather * 0.16), 1.54 - feather * 0.02]], 130, feather % 3 === 0 ? 0.95 : 0.04, 1.25)
    }
    for (let feather = 0; feather < 10; feather++) {
      const y = 0.36 - feather * 0.13
      emitStroke([[side * 0.14, y + 0.18], [side * 0.62, y], [side * (0.96 + feather * 0.045), y - 0.18], [side * 0.5, y - 0.3]], 120, feather % 4 === 0 ? 0.86 : 0.04, 0.82)
    }
  }
  // Dense facial planes preserve readability at the real HUD scale.
  for (let row = 0; row < 28; row++) {
    const y = 1.08 - row * 0.075
    const width = 0.18 + Math.sin((row / 27) * Math.PI) * 0.55
    emitStroke([[-width, y], [0, y - 0.08], [width, y]], 150, row % 7 === 0 ? 0.72 : 0.04, 0.58)
  }
  // Twin eyes and a central hooked beak are the recognition anchors.
  for (const side of [-1, 1]) {
    for (let i = 0; i < Math.round(360 * density); i++) {
      const angle = random() * Math.PI * 2
      const radius = Math.pow(random(), 1.8) * 0.1
      pushOrb(orbs, side * (0.31 + Math.cos(angle) * radius), 0.58 + Math.sin(angle) * radius * 0.48,
        0.16 + random() * 0.08, 1, 3.4, 2, 1.75, density)
    }
  }
  emitStroke([[0, 0.76], [0.16, 0.32], [0, -0.2], [-0.16, 0.32], [0, 0.76]], 760, 0.98, 2.0)
  emitStroke([[0, 0.18], [0.2, -0.16], [0, -0.54], [-0.2, -0.16], [0, 0.18]], 560, 0.9, 1.5)
  for (let bolt = 0; bolt < 9; bolt++) {
    const x = -0.48 + bolt * 0.12
    emitStroke([[x, 1.1], [x + 0.07, 0.84], [x - 0.02, 0.66], [x + 0.1, 0.42]], 95, 1, 1.85)
  }
  return orbs
}

export const stormbirdShape: PresenceShapeDefinition = {
  id: "stormbird",
  label: "Stormbird",
  buildFigure: buildStormbirdFigure,
  framing: { yaw: 0, position: [0, -0.02, 0], fitMargin: 0.82 },
}
