import * as THREE from "three"
import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"

/** Reference-reel humanoid: thousands of glowing orbs forming a contour bust. */
export function buildHumanoidBustFigure(density: number): ParticleOrb[] {
  let seed = 5103
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  const gauss = (v: number, s: number) => Math.exp(-(v * v) / (s * s))
  const orbs: ParticleOrb[] = []
  const emit = (
    x: number, y: number, z: number,
    gold: number, light: number, flow = 0, size = 1.6 + random() * 0.8,
  ) => {
    orbs.push({ x, y, z, gold, light, flow, size: size / Math.sqrt(density) })
  }

  const profile = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.08, 0.07, 0.19), new THREE.Vector3(0.27, 0.16, 0.27),
    new THREE.Vector3(0.44, 0.4, 0.35), new THREE.Vector3(0.51, 0.72, 0.40),
    new THREE.Vector3(0.52, 1.10, 0.40), new THREE.Vector3(0.44, 1.39, 0.35),
    new THREE.Vector3(0.27, 1.58, 0.24), new THREE.Vector3(0, 1.66, 0),
  ], false, "catmullrom", 0.3)

  const rows = Math.round(72 * density), columns = Math.round(200 * density)
  for (let row = 0; row < rows; row++) {
    const ring = profile.getPoint(row / rows)
    for (let col = 0; col < columns; col++) {
      const angle = (col + random() * 0.42) / columns * Math.PI * 2
      const front = Math.cos(angle), x = Math.sin(angle) * ring.x
      const nose = gauss(x, 0.12) * gauss(ring.y - 0.65, 0.26) * 0.075
      const brow = gauss(ring.y - 1.0, 0.06) * gauss(x, 0.42) * 0.025
      const z = front * ring.z + Math.max(0, front) * (nose + brow)
      const mask = gauss(x, 0.38) * gauss(ring.y - 0.61, 0.39) * THREE.MathUtils.smoothstep(front, 0.3, 0.85)
      const rim = Math.pow(Math.abs(Math.sin(angle)), 8.5)
      const shell = THREE.MathUtils.smoothstep(rim, 0.55, 0.98)
      const light = front < 0 ? 0.08 + rim * 0.35 : 0.32 + rim * 5.2 + mask * 3.4 + shell * 1.6
      if (random() < 0.018 && rim < 0.55) continue
      const jitter = (random() - 0.5) * 0.012 * (1 + shell * 0.8)
      emit(x + jitter, ring.y + Math.sin(angle * 3 + ring.y * 5) * 0.005 + jitter, z,
        mask * 0.85, light * (0.72 + random() * 0.48), 0, 1.55 + random() * 0.75 + shell * 0.35)
    }
  }
  for (let row = 0; row < Math.round(52 * density); row++) {
    const ring = profile.getPoint(row / (52 * density))
    for (let i = 0; i < Math.round(95 * density); i++) {
      const angle = (i / (95 * density) + random() * 0.08) * Math.PI * 2
      const front = Math.cos(angle)
      if (front < 0.12) continue
      const rim = Math.pow(Math.abs(Math.sin(angle)), 6.5)
      const x = Math.sin(angle) * (ring.x + 0.01)
      const z = front * ring.z
      emit(x, ring.y + (random() - 0.5) * 0.01, z, 0,
        0.55 + rim * 4.8, 0, 1.35 + random() * 0.55)
    }
  }
  for (let row = 0; row < 27 * density; row++) {
    const v = row / (27 * density) * 2 - 1
    const width = Math.sqrt(1 - v * v) * 0.34
    for (let i = 0; i < 150 * density; i++) {
      const u = i / (150 * density) * 2 - 1
      emit(u * width, 0.62 + v * 0.39 + Math.cos(u * Math.PI) * 0.013,
        0.47 - Math.abs(u) * 0.035, 1, (1 - Math.pow(Math.abs(u), 4)) * (1 - v * v) * 1.8,
        0, 1.4 + random() * 0.35)
    }
  }
  for (let i = 0; i < 2600 * density; i++) {
    const a = random() * Math.PI * 2
    const b = Math.acos(random() * 2 - 1)
    const r = Math.pow(random(), 0.5) * 0.24
    emit(
      Math.sin(b) * Math.cos(a) * r * 0.9,
      1.05 + Math.sin(b) * Math.sin(a) * r * 0.85,
      0.12 + Math.cos(b) * r * 0.7,
      1, 1.2 + (1 - r / 0.24) * 1.8, 0, 1.4 + random() * 0.7,
    )
  }
  const coreY = 0.61, coreZ = 0.445
  for (let i = 0; i < Math.round(720 * density); i++) {
    const a = random() * Math.PI * 2
    const r = Math.pow(random(), 1.8) * 0.11
    const ly = coreY + Math.sin(a) * r * 0.75 + (random() - 0.5) * 0.018
    const lx = Math.cos(a) * r * 0.55
    const lz = coreZ + Math.sin(a * 0.5) * r * 0.35
    const hot = Math.exp(-(r / 0.11) * (r / 0.11) * 2.2)
    emit(lx, ly, lz, 0, 2.8 + hot * 3.4 + random() * 0.6, 2, 2.2 + hot * 4.5 + random() * 2.2)
  }
  emit(0, coreY, coreZ, 0, 6.2, 2, 48)
  emit(0, 1.05, 0.12, 1, 0.35, 0, 90)
  for (let i = 0; i < Math.round(9200 * density); i++) {
    const headBias = Math.pow(random(), 0.55)
    const ring = profile.getPoint(0.35 + headBias * 0.62)
    const angle = random() * Math.PI * 2
    const spread = Math.pow(random(), 2.2) * 0.34
    const trail = Math.pow(random(), 0.85) * 3.6
    const back = THREE.MathUtils.smoothstep(-Math.cos(angle), 0.05, 0.55)
    const x = Math.sin(angle) * (ring.x + spread) + trail * (0.75 + random() * 0.55) * (0.35 + back * 0.65)
    const y = ring.y + spread * 0.85 + (random() - 0.5) * trail * 0.22
      + Math.sin(trail * 0.9 + ring.y) * 0.08
    const z = Math.cos(angle) * (ring.z + spread * 0.5) - trail * 0.14 - back * 0.08
    const fade = Math.exp(-trail * 0.22) * (0.28 + back * 0.55)
    emit(x, y, z, 0, (0.35 + random() * 0.72) * fade + back * 0.25, 0.38, 1.05 + random() * 1.35)
  }

  const outline = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.28, 0.16, -0.02), new THREE.Vector3(0.24, -0.10, 0.04),
    new THREE.Vector3(0.31, -0.37, 0.09), new THREE.Vector3(0.62, -0.54, 0.05),
    new THREE.Vector3(1.10, -0.65, -0.02), new THREE.Vector3(1.43, -0.89, -0.08),
    new THREE.Vector3(1.55, -1.27, -0.15),
  ])
  for (const side of [-1, 1]) {
    for (let contour = 0; contour < 7 * density; contour++) {
      for (let i = 0; i < 250 * density; i++) {
        const t = i / (250 * density), p = outline.getPoint(t)
        const inset = contour / density * 0.014
        emit(side * (p.x - inset), p.y - inset * t * 0.9, p.z + inset,
          0, (1 - contour / (9 * density)) * 2.0, 0, 1.4)
      }
    }
    for (let row = 0; row < 20 * density; row++) {
      const r = 0.17 + row / density * 0.047
      for (let col = 0; col < 180 * density; col++) {
        const angle = (col + random() * 0.8) / (180 * density) * Math.PI
        const x = side * (0.83 + Math.cos(angle) * r)
        const y = -1.54 + Math.sin(angle) * r * 0.96
        const ax = Math.abs(x)
        const top = -0.29 - 0.32 * (1 - Math.exp(-Math.pow(Math.max(0, ax - 0.25) / 0.25, 2))) - 0.32 * Math.pow(ax / 1.6, 6)
        if (ax < 0.10 || ax > 1.53 || y > top) continue
        const fade = THREE.MathUtils.smoothstep(y, -1.54, -1.24)
        emit(x, y, 0.18 + Math.sin(angle) * 0.2, 0,
          fade * (0.3 + random() * 0.35), 0, 1.35)
      }
    }
    for (let branch = 0; branch < 9; branch++) {
      for (let i = 0; i < Math.round(200 * density); i++) {
        const t = i / (200 * density)
        const y = coreY - 0.04 + t * 0.52
        const x = side * (0.02 + t * (0.11 + branch * 0.034)
          + Math.sin(t * 11 + branch * 1.3) * 0.028 * Math.sin(t * Math.PI))
        const z = coreZ - 0.06 + t * 0.12 + Math.sin(t * 8 + branch) * 0.018
        emit(x, y, z, 0.9 + random() * 0.08, 0.72 + Math.sin(t * Math.PI) * 1.05, 0, 1.45 + random() * 0.35)
      }
    }
    for (let branch = 0; branch < 5; branch++) {
      for (let i = 0; i < Math.round(165 * density); i++) {
        const t = i / (165 * density)
        const along = t * t * (3 - 2 * t)
        const x = side * (0.04 + along * (0.38 + branch * 0.05) + Math.sin(t * 9 + branch) * 0.04)
        const y = coreY - 0.02 - along * 0.14 + Math.sin(t * 6) * 0.02
        const z = coreZ - 0.04 - along * 0.06
        emit(x, y, z, 0.88, 0.58 + (1 - t) * 0.55, 0, 1.35 + random() * 0.3)
      }
    }
    for (let branch = 0; branch < 7; branch++) {
      for (let i = 0; i < Math.round(175 * density); i++) {
        const t = i / (175 * density)
        const y = coreY + 0.02 + t * 0.48
        const x = side * (0.06 + (1 - t) * 0.08 + branch * 0.012
          + Math.sin(t * 14 + branch) * 0.022 * Math.sin(t * Math.PI))
        const z = coreZ + 0.02 + t * 0.08
        emit(x, y, z, 0.93, 0.68 + Math.sin(t * Math.PI) * 0.85, 0, 1.5)
      }
    }
  }
  for (let row = 0; row < 27 * density; row++) {
    const t = row / (27 * density)
    for (let i = 0; i < 80 * density; i++) {
      const x = (i / (80 * density) * 2 - 1) * (0.23 + t * 0.09)
      const y = 0.10 - t * 0.59 - (1 - Math.pow(x / (0.23 + t * 0.09), 2)) * 0.07
      emit(x, y, 0.19, 0, 0.17 + random() * 0.18, 0, 1.25)
    }
  }
  for (let i = 0; i < 320 * density; i++) {
    const a = random() * Math.PI * 2, r = Math.pow(random(), 2) * 0.07
    emit(Math.cos(a) * r, -1.28 + Math.sin(a) * r, 0.40, 0.05, 2.3, 2, 2.4 + random() * 2.2)
  }
  emit(0, -1.28, 0.4, 0, 0.7, 2, 78)
  return orbs
}

export function buildHumanoidBustField(density: number): ParticleOrb[] {
  let seed = 9101
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  const gauss = (v: number, s: number) => Math.exp(-(v * v) / (s * s))
  const orbs: ParticleOrb[] = []
  const emit = (
    x: number, y: number, z: number,
    gold: number, light: number, flow = 1, size = 1.2,
  ) => {
    orbs.push({ x, y, z, gold, light, flow, size: size / Math.sqrt(density) })
  }

  for (const side of [-1, 1]) {
    for (let strand = 0; strand < 48 * density; strand++) {
      const band = strand / (48 * density)
      for (let i = 0; i < 200 * density; i++) {
        const t = i / (200 * density)
        const x = side * (0.95 + t * 6.4)
        const crest = Math.sin(t * 12 + side * 0.4) * 0.28
          + Math.sin(t * 27 - band * 2) * 0.11 + Math.sin(t * 51 + band * 3) * 0.04
        const y = -0.89 + t * 0.96 + crest - band * (0.28 + Math.sin(t * Math.PI) * 1.3)
        const gold = strand % 17 < 2
        const bright = gold || strand % 11 === 0
        const fade = Math.sin(t * Math.PI) * (0.28 + random() * 0.65) * (bright ? 5.5 : 0.85)
        if (bright || random() > 0.25) {
          emit(x, y, -0.75 - band * 0.7, gold ? 0.94 : 0, fade, 1, (bright ? 1.65 : 1.1) + random() * 0.8)
        }
        if (random() < 0.22) {
          emit(x, y + (random() - 0.5) * 0.22, -0.7, 0, fade * 0.55, 1, 0.9 + random())
        }
      }
    }
  }
  const peaks = [
    { x: -3.8, h: 0.85, w: 1.1 }, { x: -2.2, h: 1.2, w: 0.95 },
    { x: 2.0, h: 0.95, w: 1.0 }, { x: 3.6, h: 1.35, w: 1.15 }, { x: 5.0, h: 0.9, w: 0.9 },
  ]
  for (let i = 0; i < 5000 * density; i++) {
    const x = (random() - 0.5) * 11
    let height = 0.08, ridge = 0
    for (const peak of peaks) {
      const d = Math.abs(x - peak.x) / peak.w
      const contribution = peak.h * Math.exp(-d * d * 1.85)
      height = Math.max(height, contribution)
      ridge = Math.max(ridge, contribution * gauss(d, 0.22))
    }
    const y = -1.7 + height * random() + Math.sin(x * 7) * 0.03 * random()
    const nearRidge = ridge > height * 0.72
    emit(x, y, -1.55 - random() * 1.2,
      nearRidge && random() < 0.55 ? 0.94 : 0,
      nearRidge ? 1.8 + random() * 2 : 0.12 + random() * 0.35,
      1, nearRidge ? 1.6 : 1.0)
  }
  for (let ring = 0; ring < 5; ring++) {
    const radius = 0.98 + ring * 0.16
    for (let i = 0; i < 430 * density; i++) {
      const a = i / (430 * density) * Math.PI * 2
      if (Math.sin(a * 3 + ring * 0.7) > 0.91) continue
      const y = 0.64 + Math.cos(a) * radius
      if (y < -0.5) continue
      emit(Math.sin(a) * radius, y, -1.5, 0, 0.12 - ring * 0.014, 2, 1.15)
    }
  }
  return orbs
}

export const humanoidBustShape: PresenceShapeDefinition = {
  id: "humanoid_bust",
  label: "Humanoid bust",
  buildFigure: buildHumanoidBustFigure,
  buildField: buildHumanoidBustField,
  framing: { yaw: 0.95, position: [0.15, 0.08, 0] },
}