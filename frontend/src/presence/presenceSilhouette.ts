import { REST_TIGHTNESS, REST_TIGHTNESS_MIN } from "./presenceLifecycle"
import {
  PRESENCE_EDGE_CONTRAST_MIN,
  PRESENCE_MOTIF_CONTRAST_MIN,
  PRESENCE_OVEREXPOSURE_RATIO_MAX,
} from "./presenceQuality"
import type { ParticleOrb } from "./renderers/particleTypes"

const GRID = 48

export type SilhouetteQualityInput = {
  figure: ParticleOrb[]
  free?: ParticleOrb[]
  morph: number
  bloomStrength: number
  pointScale: number
  glow: number
  depthSoftness?: number
  /** Supporting evidence only — must not rescue an unreadable still. */
  fps?: number
  particleCount?: number
}

export type SilhouetteQualityReport = {
  overexposureRatio: number
  edgeContrast: number
  motifContrast: number
  silhouetteOccupancy: number
  restTightness: number
  readable: boolean
  failReasons: string[]
}

function mixOrbs(figure: ParticleOrb[], free: ParticleOrb[] | undefined, morph: number): ParticleOrb[] {
  if (!free || free.length === 0 || morph >= 0.999) return figure
  const n = Math.min(figure.length, free.length)
  const out: ParticleOrb[] = new Array(n)
  const m = Math.max(0, Math.min(1, morph))
  for (let i = 0; i < n; i++) {
    const a = free[i]
    const b = figure[i]
    out[i] = {
      x: a.x * (1 - m) + b.x * m,
      y: a.y * (1 - m) + b.y * m,
      z: a.z * (1 - m) + b.z * m,
      gold: a.gold * (1 - m) + b.gold * m,
      light: a.light * (1 - m) + b.light * m,
      flow: a.flow * (1 - m) + b.flow * m,
      size: a.size * (1 - m) + b.size * m,
    }
  }
  return out
}

function splat(
  core: Float32Array,
  bloomGrid: Float32Array,
  goldGrid: Float32Array,
  x: number,
  y: number,
  radius: number,
  energy: number,
  gold: number,
  bloom: number,
): void {
  const cx = Math.round((x + 2.4) / 4.8 * (GRID - 1))
  const cy = Math.round((2.2 - y) / 4.4 * (GRID - 1))
  const span = Math.max(1, Math.ceil(radius * GRID / 4.8))
  const bloomSpan = Math.max(span, Math.ceil(span * (1 + bloom * 2.2)))
  for (let dy = -bloomSpan; dy <= bloomSpan; dy++) {
    for (let dx = -bloomSpan; dx <= bloomSpan; dx++) {
      const ix = cx + dx
      const iy = cy + dy
      if (ix < 0 || iy < 0 || ix >= GRID || iy >= GRID) continue
      const dist = Math.hypot(dx, dy) / Math.max(span, 1)
      const idx = iy * GRID + ix
      if (dist <= 1) {
        const falloff = Math.exp(-dist * dist * 2.8)
        core[idx] = Math.max(core[idx], energy * falloff)
        goldGrid[idx] = Math.max(goldGrid[idx], gold * energy * falloff)
      }
      const bloomDist = Math.hypot(dx, dy) / Math.max(bloomSpan, 1)
      if (bloom > 0.001 && bloomDist <= 1) {
        const halo = energy * Math.pow(Math.min(bloom, 2), 1.85) * Math.exp(-bloomDist * bloomDist * 0.85)
        bloomGrid[idx] = Math.max(bloomGrid[idx], halo)
      }
    }
  }
}

/**
 * CPU still of a rest/engaged silhouette. High FPS or particle count cannot
 * pass a Mestor-like overexposed slab (RFC-0195 Decision 2).
 */
export function evaluateSilhouetteQuality(input: SilhouetteQualityInput): SilhouetteQualityReport {
  const failReasons: string[] = []
  const morph = Number.isFinite(input.morph) ? input.morph : 0
  if (morph < REST_TIGHTNESS_MIN - 1e-6) {
    failReasons.push(`rest tightness ${morph} hides identity (need ≥ ${REST_TIGHTNESS_MIN})`)
  }
  const orbs = mixOrbs(input.figure, input.free, morph)
  const core = new Float32Array(GRID * GRID)
  const bloomGrid = new Float32Array(GRID * GRID)
  const goldGrid = new Float32Array(GRID * GRID)
  const bloom = Math.max(0, input.bloomStrength)
  const glow = Math.max(0.01, input.glow)
  const pointScale = Math.max(0.2, input.pointScale)
  const softness = Math.max(0, Math.min(1, input.depthSoftness ?? 0))
  const sampleLimit = Math.min(orbs.length, 2400)
  const step = Math.max(1, Math.floor(orbs.length / sampleLimit))
  for (let i = 0; i < orbs.length; i += step) {
    const orb = orbs[i]
    const radius = (0.04 + orb.size * 0.02) * pointScale * (1 + softness * 0.35)
    const energy = Math.min(0.9, orb.light * glow * 0.42)
    splat(core, bloomGrid, goldGrid, orb.x, orb.y, radius, energy, orb.gold, bloom)
  }

  let occupied = 0
  let saturated = 0
  let interior = 0
  let interiorSum = 0
  let edge = 0
  let edgeSum = 0
  let goldOccupied = 0
  let motifGold = 0
  let motifFill = 0
  for (let y = 1; y < GRID - 1; y++) {
    for (let x = 1; x < GRID - 1; x++) {
      const idx = y * GRID + x
      const v = Math.min(1.6, core[idx] + bloomGrid[idx])
      if (v <= 0.08) continue
      occupied += 1
      if (v > 0.92 && bloomGrid[idx] > 0.55) saturated += 1
      const neighborEmpty =
        core[idx - 1] + bloomGrid[idx - 1] <= 0.08
        || core[idx + 1] + bloomGrid[idx + 1] <= 0.08
        || core[idx - GRID] + bloomGrid[idx - GRID] <= 0.08
        || core[idx + GRID] + bloomGrid[idx + GRID] <= 0.08
      if (neighborEmpty) {
        edge += 1
        edgeSum += v
      } else {
        interior += 1
        interiorSum += v
      }
      if (goldGrid[idx] > 0.12) {
        goldOccupied += 1
        motifGold += goldGrid[idx]
      } else {
        motifFill += v
      }
    }
  }

  const overexposureRatio = occupied > 0 ? saturated / occupied : 1
  const edgeMean = edge > 0 ? edgeSum / edge : 0
  const interiorMean = interior > 0 ? interiorSum / interior : edgeMean
  const edgeContrast = Math.abs(edgeMean - interiorMean) / Math.max(0.18, interiorMean)
  const motifContrast = goldOccupied > 0
    ? motifGold / goldOccupied / Math.max(0.18, (motifFill / Math.max(1, occupied - goldOccupied)))
    : 0
  const silhouetteOccupancy = occupied / (GRID * GRID)

  if (overexposureRatio > PRESENCE_OVEREXPOSURE_RATIO_MAX) {
    failReasons.push(
      `overexposure ${overexposureRatio.toFixed(3)} > ${PRESENCE_OVEREXPOSURE_RATIO_MAX} (slab)`,
    )
  }
  if (edgeContrast < PRESENCE_EDGE_CONTRAST_MIN) {
    failReasons.push(
      `edge contrast ${edgeContrast.toFixed(3)} < ${PRESENCE_EDGE_CONTRAST_MIN}`,
    )
  }
  if (goldOccupied > 8 && motifContrast < PRESENCE_MOTIF_CONTRAST_MIN) {
    failReasons.push(
      `motif contrast ${motifContrast.toFixed(3)} < ${PRESENCE_MOTIF_CONTRAST_MIN} (rings washed)`,
    )
  }
  if (silhouetteOccupancy < 0.02) {
    failReasons.push("silhouette occupancy too low (anonymous cloud / empty still)")
  }

  const fps = input.fps
  const particles = input.particleCount
  if (failReasons.length > 0 && ((fps !== undefined && fps >= 60) || (particles !== undefined && particles >= 20000))) {
    failReasons.push("high FPS / particle count does not rescue an unreadable silhouette")
  }

  return {
    overexposureRatio,
    edgeContrast,
    motifContrast,
    silhouetteOccupancy,
    restTightness: morph,
    readable: failReasons.length === 0,
    failReasons,
  }
}

export function restSilhouetteOrAnonymous(morph: number): "silhouette" | "anonymous" {
  return morph >= REST_TIGHTNESS_MIN ? "silhouette" : "anonymous"
}

export { REST_TIGHTNESS }
