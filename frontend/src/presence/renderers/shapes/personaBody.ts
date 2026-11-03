import type { ParticleOrb } from "../particleTypes"

type V = readonly [number, number, number]
export type PersonaBody = { points: ParticleOrb[]; headPivot: V; anatomy: "stag" | "bird" | "dragon" | "mythic" }
const BIRDS = new Set(["anzu", "nabu", "bragi"])

/** Authored heads stay intact; closed anatomical surfaces supply the rest of each living cloud. */
export function buildPersonaBody(head: readonly ParticleOrb[], persona: string): PersonaBody {
  const anatomy = persona === "eir" ? "stag" : persona === "veles" ? "dragon" : BIRDS.has(persona) ? "bird" : "mythic"
  const quadruped = anatomy === "stag" || anatomy === "dragon"
  const headScale = quadruped ? 0.48 : anatomy === "bird" ? 0.53 : 0.42
  const headCenter: V = quadruped ? [0.86, 1.26, 0.14] : anatomy === "bird" ? [0, 1.03, 0.14] : [0, 1.42, 0.1]
  const headPivot: V = [headCenter[0], headCenter[1] - headScale * 1.1, headCenter[2]]
  const points = head.map(p => ({ ...p, x: p.x * headScale + headCenter[0], y: p.y * headScale + headCenter[1],
    z: p.z * headScale + headCenter[2], size: p.size * 0.8, flow: 0 }))
  let seed = 5103 + [...persona].reduce((n, c) => n + c.charCodeAt(0), 0)
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
  const palette = head.filter(p => p.color && p.light > 0.55)
  const add = (x: number, y: number, z: number, flow = -10, ridge = 0) => {
    const source = palette.length ? palette[Math.floor(random() * palette.length)] : undefined
    const rgb = source?.color || [0.08, 0.4, 0.65, 1]
    const exposure = Math.min(2.3, 0.72 / Math.max(0.05, rgb[0], rgb[1], rgb[2]))
    const front = 0.52 + Math.max(0, z) * 0.7
    points.push({ x, y, z, flow, gold: 0, size: 1.7 + random() * 0.4,
      light: front * (1.4 + ridge * 0.9), color: [rgb[0] * exposure, rgb[1] * exposure, rgb[2] * exposure, 1] })
  }
  const ellipsoid = (center: V, radii: V, flow = -10, rows = 52, columns = 84) => {
    for (let row = 1; row < rows; row++) {
      const latitude = row / rows * Math.PI
      for (let col = 0; col < columns; col++) {
        const angle = (col + random() * 0.35) / columns * Math.PI * 2
        const contour = Math.sin(latitude)
        const fur = 1 + Math.sin(angle * 18 + latitude * 35) * 0.008
        add(center[0] + Math.cos(angle) * radii[0] * contour * fur, center[1] + Math.cos(latitude) * radii[1],
          center[2] + Math.sin(angle) * radii[2] * contour * fur, flow, Math.pow(Math.abs(Math.cos(angle)), 8) * 0.6)
      }
    }
  }
  const tube = (path: V[], radii: number[], flow = -10, rows = 65, sides = 22) => {
    for (let row = 0; row <= rows; row++) {
      const at = row / rows * (path.length - 1)
      const section = Math.min(path.length - 2, Math.floor(at)), t = at - section
      const a = path[section], b = path[section + 1]
      const dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2]
      const length = Math.hypot(dx, dy, dz) || 1
      // Perpendicular frame works for vertical limbs and horizontal tails alike.
      const u: V = Math.abs(dy / length) > 0.9 ? [1, 0, 0] : [-dy / Math.hypot(dx, dy), dx / Math.hypot(dx, dy), 0]
      const v: V = [-dz / length * u[1], dz / length * u[0], (dx * u[1] - dy * u[0]) / length]
      const radius = radii[section] * (1 - t) + radii[section + 1] * t
      for (let col = 0; col < sides; col++) {
        const angle = (col + random() * 0.25) / sides * Math.PI * 2
        const c = Math.cos(angle) * radius, s = Math.sin(angle) * radius
        add(a[0] + dx * t + u[0] * c + v[0] * s, a[1] + dy * t + u[1] * c + v[1] * s,
          a[2] + dz * t + u[2] * c + v[2] * s, flow, col % 8 === 0 ? 0.65 : 0)
      }
    }
  }
  const feathers = (side: number, bird = true) => {
    for (let feather = 0; feather < 15; feather++) {
      const f = feather / 14
      const start: V = [side * 0.38, 0.3 - f * 0.35, -0.04]
      const end: V = [side * (0.62 + (1 - f) * (bird ? 0.6 : 0.35)), -0.5 - f * 0.75, -0.18]
      tube([start, [side * (0.82 + (1 - f) * 0.25), -0.1 - f * 0.45, 0.03], end], [0.065, 0.085, 0.004], side < 0 ? -11 : -12, 38, 9)
    }
  }
  if (quadruped) {
    ellipsoid([-0.22, -0.15, 0], [0.98, 0.48, 0.38])
    ellipsoid([0.5, -0.08, 0.03], [0.38, 0.55, 0.4])
    tube([[0.48, 0.05, 0.02], [0.64, 0.5, 0.05], [0.86, 0.86, 0.12]], [0.33, 0.28, 0.19], -10, 75, 56)
    for (const x of [-0.88, 0.48]) for (const side of [-1, 1]) {
      const z = side * 0.25
      const knee = (x < 0 ? x + 0.18 : x - 0.05) + side * 0.1
      const foot = x + (side > 0 ? 0.16 : -0.17)
      tube([[x, -0.38, z], [knee, -0.87, z], [foot, -1.52, z + 0.02]], [0.16, 0.09, 0.052], side < 0 ? -11 : -12, 72, 24)
      ellipsoid([foot + 0.02, -1.57, z + 0.05], [0.105, 0.1, 0.105], -10, 16, 26)
    }
    if (anatomy === "stag") {
      tube([[-1.05, -0.03, 0], [-1.27, 0.08, 0.02], [-1.38, -0.09, 0.03]], [0.1, 0.075, 0.008], -13, 35, 18)
      // Lit shoulder and flank contours give the deer a readable standing silhouette.
      for (const z of [-0.32, 0.34]) tube([[-0.9, 0.06, z], [-0.3, 0.23, z], [0.37, 0.25, z]], [0.012, 0.016, 0.012], -10, 110, 6)
    } else {
      tube([[-1, -0.05, 0], [-1.55, 0.02, -0.1], [-1.72, 0.48, -0.2], [-1.35, 0.75, -0.28]], [0.24, 0.16, 0.08, 0.008], -13, 140, 32)
      for (const side of [-1, 1]) for (let rib = 0; rib < 8; rib++) {
        const t = rib / 7
        tube([[0.08, 0.05, side * 0.2], [-0.25 - t * 1.1, 0.9 + Math.sin(t * Math.PI) * 0.65, side * 0.48], [-0.72 - t * 0.65, 0.04 + t * 0.34, side * 0.54]],
          [0.05, 0.025, 0.006], side < 0 ? -11 : -12, 85, 9)
        for (let membrane = 0; membrane < 8; membrane++) {
          const k = membrane / 8
          tube([[-0.25 - t * 1.1, 0.9 + Math.sin(t * Math.PI) * 0.65, side * 0.48], [-0.62 - t * 0.7, 0.14 + k * 0.55, side * (0.5 + k * 0.08)]],
            [0.009, 0.004], side < 0 ? -11 : -12, 24, 4)
        }
      }
    }
  } else if (anatomy === "bird") {
    ellipsoid([0, -0.22, 0], [persona === "nabu" ? 0.65 : 0.56, 0.9, 0.38])
    ellipsoid([0, 0.5, 0.06], [0.3, 0.47, 0.27], -10, 35, 60)
    feathers(-1); feathers(1)
    for (let tail = -4; tail <= 4; tail++) tube([[tail * 0.04, -0.78, -0.14], [tail * 0.08, -1.45, -0.18]], [0.055, 0.008], -13, 55, 12)
    for (const side of [-1, 1]) {
      tube([[side * 0.25, -0.89, 0.1], [side * 0.26, -1.43, 0.12]], [0.065, 0.035], -10, 42, 18)
      for (let toe = -1; toe <= 1; toe++) tube([[side * 0.26, -1.4, 0.12], [side * 0.26 + toe * 0.13, -1.52, 0.28]], [0.03, 0.007], -10, 20, 9)
    }
  } else {
    const gown = ["themis", "maia", "umi", "enki", "aegir"].includes(persona)
    ellipsoid([0, 0.37, 0], [0.5, 0.62, 0.27])
    tube([[0, 0.75, 0], [0, 1.01, 0.05]], [0.19, 0.16], -10, 28, 38)
    ellipsoid([0, -0.26, 0], [0.37, 0.43, 0.25], -10, 36, 66)
    for (const side of [-1, 1]) {
      ellipsoid([side * 0.49, 0.63, 0], [0.23, 0.2, 0.28], -10, 22, 36)
      tube([[side * 0.56, 0.57, 0], [side * 0.76, 0.06, 0.05], [side * 0.74, -0.38, 0.18]], [0.16, 0.11, 0.07], side < 0 ? -11 : -12, 70, 23)
      ellipsoid([side * 0.74, -0.45, 0.2], [0.085, 0.13, 0.055], -10, 18, 22)
      for (let finger = 0; finger < 4; finger++) tube([[side * 0.71 + finger * side * 0.022, -0.48, 0.22], [side * 0.71 + finger * side * 0.024, -0.66, 0.23]], [0.016, 0.009], -10, 18, 5)
      tube([[side * 0.23, -0.43, 0], [side * 0.24, -0.98, 0.035], [side * 0.25, -1.58, 0.04]], [0.21, 0.135, 0.085], -10, 78, 27)
      ellipsoid([side * 0.25, -1.64, 0.15], [0.14, 0.11, 0.26], -10, 20, 30)
    }
    if (gown) for (let row = 0; row < 85; row++) {
      const t = row / 84
      for (let col = 0; col < 100; col++) {
        const a = col / 100 * Math.PI * 2
        const r = 0.32 + t * 0.34 + Math.sin(a * 18) * 0.022
        add(Math.cos(a) * r, -0.24 - t * 1.3, Math.sin(a) * r * 0.55 - 0.04, -10, col % 6 === 0 ? 0.8 : 0)
      }
    }
    // Complete silhouettes retain their own regalia, rather than sharing one anonymous body.
    if (["enki", "aegir", "hermes", "themis", "heimdall"].includes(persona)) {
      tube([[0.86, -1.65, 0.17], [0.86, 1.08, 0.17]], [0.026, 0.026], -10, 150, 10)
      if (persona === "enki" || persona === "aegir") for (const side of [-1, 0, 1]) tube([[0.86, 0.7, 0.17], [0.86 + side * 0.2, 1.02, 0.17], [0.86 + side * 0.2, 1.28, 0.17]], [0.025, 0.022, 0.005], -10, 45, 9)
      if (persona === "themis") {
        tube([[0.58, 0.8, 0.18], [1.14, 0.8, 0.18]], [0.016, 0.016], -10, 50, 8)
        for (const x of [0.58, 1.14]) { tube([[x, 0.8, 0.18], [x, 0.45, 0.18]], [0.008, 0.008], -10, 25, 6); ellipsoid([x, 0.43, 0.18], [0.15, 0.04, 0.12], -10, 14, 28) }
      }
      if (persona === "heimdall") tube([[0.76, -0.35, 0.2], [1.12, -0.13, 0.22], [1.28, 0.2, 0.23]], [0.05, 0.11, 0.2], -10, 55, 28)
      if (persona === "hermes") { feathers(-1, false); feathers(1, false) }
    }
    if (persona === "vulcan") {
      tube([[-0.77, -0.68, 0.2], [-0.77, 0.2, 0.2]], [0.05, 0.05], -10, 60, 14)
      ellipsoid([-0.77, 0.27, 0.2], [0.34, 0.15, 0.14], -10, 25, 44)
    }
    if (["mestor", "heimdall", "vulcan"].includes(persona)) for (const side of [-1, 1]) tube([[side * 0.4, 0.72, -0.11], [side * 0.7, 0.45, -0.2], [side * 0.63, -1.35, -0.3]], [0.13, 0.17, 0.03], -13, 90, 30)
  }
  return { points, headPivot, anatomy }
}
