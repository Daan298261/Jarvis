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
