import * as THREE from "three"
import { buildHumanoidBustField, buildHumanoidBustFigure } from "./shapes/humanoidBust"
import { particleFragmentShader, particleVertexShader } from "./morphableOrbCloud"

export { particleFragmentShader, particleVertexShader }
export {
  registerPresenceShape,
  listPresenceShapes,
  resolvePresenceShape,
  presenceShapeIdForAvatar,
  DEFAULT_PRESENCE_SHAPE_ID,
} from "./shapes/catalog"
export type { ParticleOrb, PresenceShapeDefinition, PresenceShapeId } from "./particleTypes"

/** @deprecated Prefer createMorphablePresenceSystem — kept for transitional imports. */
export function createParticleBust(density: number, material: THREE.ShaderMaterial) {
  const figure = orbsToPoints(buildHumanoidBustFigure(density), material)
  const field = orbsToPoints(buildHumanoidBustField(density), material)
  // Split figure roughly into head/body by y for legacy callers.
  return { head: figure, body: figure, field }
}

/**
 * Dense, face-forward particle portrait recovered from the experimental bust.
 * This deliberately does not participate in avatar morphing: it is a distinct
 * appearance mode, so the established humanoid renderer stays available.
 */
export function createApexParticleBust(density: number, material: THREE.ShaderMaterial) {
  let state = 5103
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 4294967296
  }
  const head: { x: number; y: number; z: number; gold: number; light: number; flow: number; size: number }[] = []
  const body: typeof head = []
  const field: typeof head = []
  const emit = (target: typeof head, x: number, y: number, z: number, gold: number, light: number, flow = 0, size = 1.5) => {
    target.push({ x, y, z, gold, light, flow, size })
  }

  // Portrait surface: a softened anatomical oval with a bright facial mask and
  // discontinuous contour lines rather than a latitude/longitude grid.
  const rows = Math.round(54 * density)
  const columns = Math.round(132 * density)
  for (let row = 0; row < rows; row++) {
    const t = row / Math.max(1, rows - 1)
    const y = 1.58 - t * 1.72
    const radius = 0.10 + Math.sin(Math.PI * t) * (0.41 - t * 0.045)
    for (let column = 0; column < columns; column++) {
      const angle = (column + random() * 0.6) / columns * Math.PI * 2
      const x = Math.sin(angle) * radius
      const front = Math.cos(angle)
      const mask = Math.exp(-(x * x) / 0.12 - ((y - 0.66) ** 2) / 0.22) * Math.max(0, front)
      if (random() < 0.045 && mask < 0.2) continue
      const nose = Math.exp(-(x * x) / 0.015 - ((y - 0.68) ** 2) / 0.12) * Math.max(0, front) * 0.07
      const rim = Math.pow(Math.abs(Math.sin(angle)), 12)
      emit(head, x, y, front * (0.23 + radius * 0.32) + nose, mask,
        0.2 + rim * 2.6 + mask * 2.5, 0, 1.15 + random() * 0.75)
    }
  }
  // Shoulder arcs, sternum filaments, and the loose flowing field make this a
  // head-and-shoulders presence rather than another generic orb cloud.
  const shoulderRows = Math.round(32 * density)
  for (const side of [-1, 1]) {
    for (let row = 0; row < shoulderRows; row++) {
      const u = row / Math.max(1, shoulderRows - 1)
      const y = -0.24 - u * 1.17
      const edge = 0.25 + u * 1.2
      for (let i = 0; i < Math.round(105 * density); i++) {
        const v = i / Math.max(1, Math.round(105 * density) - 1)
        const x = side * (0.16 + v * edge)
        const contour = Math.exp(-((v - 0.82) ** 2) / 0.12)
        emit(body, x, y - (v ** 3) * 0.19, 0.12 + contour * 0.13,
          0, 0.15 + contour * 1.6, 0, 1.05 + random() * 0.6)
      }
    }
    for (let branch = 0; branch < 6; branch++) {
      for (let i = 0; i < Math.round(105 * density); i++) {
        const t = i / Math.max(1, Math.round(105 * density) - 1)
        emit(body, side * (0.02 + t * (0.05 + branch * 0.024) + Math.sin(t * 13 + branch) * 0.022),
          -1.26 + t * 1.23, 0.31, 0.88, 0.48 + Math.sin(t * Math.PI) * 0.9, 0, 1.25)
      }
    }
  }
  for (const side of [-1, 1]) {
    for (let strand = 0; strand < Math.round(38 * density); strand++) {
      const band = strand / Math.max(1, Math.round(38 * density) - 1)
      for (let i = 0; i < Math.round(138 * density); i++) {
        const t = i / Math.max(1, Math.round(138 * density) - 1)
        const x = side * (0.92 + t * 5.2)
        const y = -0.92 + t * 0.94 + Math.sin(t * 12 + band * 5) * 0.24 - band * 0.48
        const bright = strand % 15 < 2
        if (bright || random() > 0.26) emit(field, x, y, -0.8 - band * 0.55,
          bright ? 0.9 : 0, (bright ? 3.2 : 0.55) * Math.sin(t * Math.PI), 1, bright ? 1.55 : 1.0)
      }
    }
  }
  return {
    head: orbsToPoints(head, material),
    body: orbsToPoints(body, material),
    field: orbsToPoints(field, material),
  }
}

function orbsToPoints(
  orbs: { x: number; y: number; z: number; gold: number; light: number; flow: number; size: number }[],
  material: THREE.ShaderMaterial,
) {
  const position: number[] = []
  const sizes: number[] = []
  const golds: number[] = []
  const lights: number[] = []
  const flows: number[] = []
  const seeds: number[] = []
  orbs.forEach((orb, i) => {
    position.push(orb.x, orb.y, orb.z)
    sizes.push(orb.size)
    golds.push(orb.gold)
    lights.push(orb.light)
    flows.push(orb.flow)
    seeds.push((i * 0.618033) % 1)
  })
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(position, 3))
  geometry.setAttribute("aPos", new THREE.Float32BufferAttribute(position, 3))
  geometry.setAttribute("bPos", new THREE.Float32BufferAttribute(position.slice(), 3))
  geometry.setAttribute("aSize", new THREE.Float32BufferAttribute(sizes, 1))
  geometry.setAttribute("bSize", new THREE.Float32BufferAttribute(sizes.slice(), 1))
  geometry.setAttribute("aGold", new THREE.Float32BufferAttribute(golds, 1))
  geometry.setAttribute("bGold", new THREE.Float32BufferAttribute(golds.slice(), 1))
  geometry.setAttribute("aLight", new THREE.Float32BufferAttribute(lights, 1))
  geometry.setAttribute("bLight", new THREE.Float32BufferAttribute(lights.slice(), 1))
  geometry.setAttribute("aFlow", new THREE.Float32BufferAttribute(flows, 1))
  geometry.setAttribute("bFlow", new THREE.Float32BufferAttribute(flows.slice(), 1))
  geometry.setAttribute("aSeed", new THREE.Float32BufferAttribute(seeds, 1))
  return new THREE.Points(geometry, material)
}
