import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb } from "./figureKit"

/** Cyan orb inside a rotating wireframe cube with flowing code-lines. */
export function buildCodeCubeFigure(density: number): ParticleOrb[] {
  const random = makeRng(4604)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(1600 * density), 0.42, 0.1, 0.15, 1.5, 0, 1.45, density)
  const extent = 0.78
  const corners: Array<[number, number, number]> = []
  for (const x of [-extent, extent]) {
    for (const y of [-extent + 0.1, extent + 0.1]) {
      for (const z of [-extent, extent]) corners.push([x, y, z])
    }
  }
  const edges: Array<[number, number]> = [
    [0, 1], [2, 3], [4, 5], [6, 7],
    [0, 2], [1, 3], [4, 6], [5, 7],
    [0, 4], [1, 5], [2, 6], [3, 7],
  ]
  const steps = Math.round(36 * density)
  for (const [a, b] of edges) {
    const p = corners[a]
    const q = corners[b]
    for (let s = 0; s <= steps; s++) {
      const t = s / steps
      pushOrb(
        orbs,
        p[0] + (q[0] - p[0]) * t,
        p[1] + (q[1] - p[1]) * t,
        p[2] + (q[2] - p[2]) * t,
        t > 0.5 ? 1 : 0.2,
        1.45,
        0.48,
        1.2,
        density,
      )
    }
  }
  return orbs
}

export const codeCubeShape: PresenceShapeDefinition = {
  id: "code_cube",
  label: "Code cube",
  buildFigure: buildCodeCubeFigure,
  framing: { yaw: 0.45, position: [0, 0.08, 0] },
}
