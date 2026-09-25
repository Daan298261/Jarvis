import type { ParticleOrb } from "../particleTypes"

export function makeRng(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 4294967296
  }
}

export function pushOrb(
  orbs: ParticleOrb[],
  x: number,
  y: number,
  z: number,
  gold: number,
  light: number,
  flow: number,
  size: number,
  density: number,
): void {
  orbs.push({
    x,
    y,
    z,
    gold,
    light,
    flow,
    size: size / Math.sqrt(Math.max(0.25, density)),
  })
}

export function fillSphere(
  orbs: ParticleOrb[],
  random: () => number,
  count: number,
  radius: number,
  yOffset: number,
  gold: number,
  light: number,
  flow: number,
  size: number,
  density: number,
  squash = 0.92,
): void {
  for (let i = 0; i < count; i++) {
    const a = random() * Math.PI * 2
    const b = Math.acos(random() * 2 - 1)
    const shell = Math.pow(random(), 0.48)
    const r = shell * radius
    const core = shell < 0.42 ? 1 : gold
    pushOrb(
      orbs,
      Math.sin(b) * Math.cos(a) * r,
      Math.sin(b) * Math.sin(a) * r * squash + yOffset,
      Math.cos(b) * r,
      core,
      core ? light + (1 - shell) : light * 0.55,
      shell < 0.25 ? 2 : flow,
      size * (0.8 + random() * 0.5),
      density,
    )
  }
}

export function ring(
  orbs: ParticleOrb[],
  random: () => number,
  count: number,
  radius: number,
  y: number,
  gold: number,
  light: number,
  flow: number,
  size: number,
  density: number,
  tilt = 0,
): void {
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2
    const x = Math.cos(a) * radius
    const z = Math.sin(a) * radius
    const y2 = y + x * Math.sin(tilt)
    const j = (random() - 0.5) * 0.012
    pushOrb(orbs, x + j, y2, z * Math.cos(tilt) + j, gold, light, flow, size, density)
  }
}
