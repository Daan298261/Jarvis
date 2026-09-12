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

  // Explicit front-view landmarks make a human cranium with cheekbones, jaw
  // and chin. Sampling the old spline by curve length bunched rings into a
  // rounded capsule and lost the reference silhouette.
  const profile = [
    { t: 0, x: 0.05, y: 0.18, z: 0.16 },
    { t: 0.12, x: 0.34, y: 0.35, z: 0.29 },
    { t: 0.3, x: 0.51, y: 0.63, z: 0.38 },
    { t: 0.56, x: 0.59, y: 1.02, z: 0.42 },
    { t: 0.78, x: 0.55, y: 1.34, z: 0.39 },
    { t: 0.93, x: 0.37, y: 1.56, z: 0.29 },
    { t: 1, x: 0.08, y: 1.65, z: 0.1 },
  ]
  const profileCurve = new THREE.CatmullRomCurve3(
    profile.map((point) => new THREE.Vector3(point.x, point.y, point.z)),
    false,
    "catmullrom",
    0.56,
  )
  const headRing = (t: number) => profileCurve.getPoint(THREE.MathUtils.clamp(t, 0, 1))

  const rows = Math.round(88 * density), columns = Math.round(236 * density)
  for (let row = 0; row < rows; row++) {
    const ring = headRing(row / rows)
    for (let col = 0; col < columns; col++) {
      const angle = (col + random() * 0.42) / columns * Math.PI * 2
      const front = Math.cos(angle), x = Math.sin(angle) * ring.x
      const nose = gauss(x, 0.14) * gauss(ring.y - 0.82, 0.29) * 0.07
      const brow = gauss(ring.y - 1.12, 0.07) * gauss(x, 0.46) * 0.022
      const z = front * ring.z + Math.max(0, front) * (nose + brow)
      const mask = gauss(x, 0.43) * gauss(ring.y - 0.88, 0.46) * THREE.MathUtils.smoothstep(front, 0.28, 0.86)
      const rim = Math.pow(Math.abs(Math.sin(angle)), 8.5)
      const shell = THREE.MathUtils.smoothstep(rim, 0.55, 0.98)
      const light = front < 0 ? 0.08 + rim * 0.35 : 0.28 + rim * 3.8 + mask * 1.65 + shell * 1.25
      if (random() < 0.018 && rim < 0.55) continue
      const jitter = (random() - 0.5) * 0.012 * (1 + shell * 0.8)
      emit(x + jitter, ring.y + Math.sin(angle * 3 + ring.y * 5) * 0.005 + jitter, z,
        mask * 0.85, light * (0.72 + random() * 0.48), 0, 1.55 + random() * 0.75 + shell * 0.35)
    }
  }
  for (let row = 0; row < Math.round(52 * density); row++) {
    const ring = headRing(row / (52 * density))
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
  for (let row = 0; row < 34 * density; row++) {
    const v = row / (34 * density) * 2 - 1
    const width = Math.sqrt(1 - v * v) * 0.48
    for (let i = 0; i < 190 * density; i++) {
      const u = i / (190 * density) * 2 - 1
      const heat = (1 - Math.pow(Math.abs(u), 3)) * (1 - v * v)
      emit(u * width, 0.88 + v * 0.5 + Math.cos(u * Math.PI) * 0.012,
        0.48 - Math.abs(u) * 0.028, heat * 0.92, 0.42 + heat * 1.02,
        0, 1.15 + random() * 0.3)
    }
  }
  // A diffuse amber volume behind the scan bands. It reads as neural heat, not
  // as the single white flashlight that previously erased the face.
  for (let i = 0; i < 5600 * density; i++) {
    const a = random() * Math.PI * 2
    const b = Math.acos(random() * 2 - 1)
    const r = Math.pow(random(), 0.62)
    emit(
      Math.sin(b) * Math.cos(a) * r * 0.42,
      0.9 + Math.sin(b) * Math.sin(a) * r * 0.51,
      0.19 + Math.cos(b) * r * 0.15,
      0.78 + random() * 0.16, 0.34 + (1 - r) * 1.02, 0, 0.95 + random() * 0.5,
    )
  }
  const coreY = 0.9, coreZ = 0.45
  for (let i = 0; i < Math.round(980 * density); i++) {
    const a = random() * Math.PI * 2
    const r = Math.pow(random(), 1.45) * 0.2
    const ly = coreY + Math.sin(a) * r * 1.35 + (random() - 0.5) * 0.024
    const lx = Math.cos(a) * r
    const lz = coreZ + Math.sin(a * 0.5) * r * 0.22
    const hot = Math.exp(-(r / 0.2) * (r / 0.2) * 1.8)
    emit(lx, ly, lz, 0.92, 0.72 + hot * 1.35 + random() * 0.35, 2, 1.25 + hot * 0.95 + random() * 0.65)
  }

  // Dense interior population: these dim particles make the face read as mass
  // rather than a wire shell while the brighter rings retain its anatomy.
  for (let i = 0; i < Math.round(18000 * density); i++) {
    const azimuth = random() * Math.PI * 2
    const elevation = Math.acos(random() * 2 - 1)
    const r = Math.cbrt(random())
    const vertical = Math.cos(elevation)
    const jaw = THREE.MathUtils.lerp(0.72, 1, THREE.MathUtils.smoothstep(vertical, -0.45, 0.2))
    emit(
      Math.sin(elevation) * Math.cos(azimuth) * r * 0.54 * jaw,
      0.88 + vertical * r * 0.76,
      0.02 + Math.sin(elevation) * Math.sin(azimuth) * r * 0.34,
      random() < 0.06 ? 0.75 : 0,
      0.18 + (1 - r) * 0.5 + random() * 0.18,
      0,
      1.05 + random() * 0.75,
    )
  }

  // A second interior population joins the neck, chest, and broad shoulders.
  for (let i = 0; i < Math.round(18000 * density); i++) {
    const y = -1.32 + random() * 1.57
    const shoulderBand = Math.exp(-Math.pow((y + 0.52) / 0.48, 2))
    const width = 0.29 + shoulderBand * 1.24 + THREE.MathUtils.smoothstep(-y, 0.08, 1.3) * 0.22
    const normalizedX = (random() * 2 - 1) * Math.pow(random(), 0.34)
    const x = normalizedX * width
    const edge = Math.abs(normalizedX)
    const depth = (0.16 + shoulderBand * 0.16) * Math.sqrt(Math.max(0, 1 - edge * edge))
    emit(
      x,
      y,
      0.03 + (random() * 2 - 1) * depth,
      random() < 0.035 ? 0.72 : 0,
      0.18 + (1 - edge) * 0.42 + random() * 0.2,
      0,
      1 + random() * 0.7,
    )
  }

  for (let i = 0; i < Math.round(6500 * density); i++) {
    const headBias = Math.pow(random(), 0.55)
    const ring = headRing(0.3 + headBias * 0.67)
    const angle = random() * Math.PI * 2
    const spread = Math.pow(random(), 1.9) * 0.5
    const trail = (random() - 0.5) * 1.2
    const back = THREE.MathUtils.smoothstep(-Math.cos(angle), 0.05, 0.55)
    const x = Math.sin(angle) * (ring.x + spread) + trail * (0.26 + back * 0.2)
    const y = ring.y + spread * 0.65 + (random() - 0.5) * Math.abs(trail) * 0.28
      + Math.sin(trail * 1.8 + ring.y) * 0.05
    const z = Math.cos(angle) * (ring.z + spread * 0.45) - Math.abs(trail) * 0.08 - back * 0.06
    const fade = Math.exp(-Math.abs(trail) * 0.55) * (0.3 + back * 0.52)
    emit(x, y, z, 0, (0.35 + random() * 0.72) * fade + back * 0.25, 0.38, 1.05 + random() * 1.35)
  }

  const outline = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.27, 0.20, -0.02), new THREE.Vector3(0.25, 0.02, 0.04),
    new THREE.Vector3(0.36, -0.20, 0.09), new THREE.Vector3(0.70, -0.34, 0.05),
    new THREE.Vector3(1.14, -0.48, -0.02), new THREE.Vector3(1.48, -0.70, -0.08),
    new THREE.Vector3(1.61, -1.08, -0.15),
  ])
  for (const side of [-1, 1]) {
    for (let contour = 0; contour < 11 * density; contour++) {
      for (let i = 0; i < 250 * density; i++) {
        const t = i / (250 * density), p = outline.getPoint(t)
        const inset = contour / density * 0.014
        emit(side * (p.x - inset), p.y - inset * t * 0.9, p.z + inset,
          0, (1 - contour / (14 * density)) * 2.25, 0, 1.4)
      }
    }
    for (let row = 0; row < 28 * density; row++) {
      const r = 0.17 + row / density * 0.047
      for (let col = 0; col < 180 * density; col++) {
        const angle = (col + random() * 0.8) / (180 * density) * Math.PI
        const x = side * (0.83 + Math.cos(angle) * r)
        const y = -1.42 + Math.sin(angle) * r * 0.96
        const ax = Math.abs(x)
        const top = -0.05 - 0.3 * (1 - Math.exp(-Math.pow(Math.max(0, ax - 0.25) / 0.25, 2))) - 0.3 * Math.pow(ax / 1.65, 6)
        if (ax < 0.10 || ax > 1.53 || y > top) continue
        const fade = THREE.MathUtils.smoothstep(y, -1.42, -1.1)
        emit(x, y, 0.18 + Math.sin(angle) * 0.2, 0,
          fade * (0.44 + random() * 0.42), 0, 1.35)
      }
    }
  }
  for (let row = 0; row < 27 * density; row++) {
    const t = row / (27 * density)
    for (let i = 0; i < 80 * density; i++) {
      const x = (i / (80 * density) * 2 - 1) * (0.23 + t * 0.09)
      const y = 0.18 - t * 0.46 - (1 - Math.pow(x / (0.23 + t * 0.09), 2)) * 0.05
      emit(x, y, 0.19, 0, 0.17 + random() * 0.18, 0, 1.25)
    }
  }
  // Gold circuitry descends from the face through the neck and sternum, as in
  // the reference, without adding a separate glowing chest orb.
  for (const side of [-1, 1]) {
    for (let branch = 0; branch < 12; branch++) {
      for (let i = 0; i < Math.round(185 * density); i++) {
        const t = i / (185 * density)
        const spread = 0.018 + t * (0.025 + branch * 0.012)
        const x = side * (spread + Math.sin(t * 16 + branch * 0.9) * 0.012 * Math.sin(t * Math.PI))
        const y = 0.2 - t * 1.44
        const z = 0.37 - t * 0.08 + Math.sin(t * 9 + branch) * 0.012
        emit(x, y, z, 0.9, 0.58 + (1 - t) * 0.72 + Math.sin(t * Math.PI) * 0.45, 0, 1.15 + random() * 0.35)
      }
    }
  }
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
  framing: { yaw: 0.025, position: [0, -0.1, 0] },
}
