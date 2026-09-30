import { REST_TIGHTNESS, REST_TIGHTNESS_MIN, lifecycleMorphBlend } from "./presenceLifecycle"
import {
  PRESENCE_EDGE_CONTRAST_MIN,
  PRESENCE_MOTIF_CONTRAST_MIN,
  PRESENCE_OVEREXPOSURE_RATIO_MAX,
} from "./presenceQuality"
import type { ParticleOrb } from "./renderers/particleTypes"

const GRID = 48

export type SilhouetteQualityInput = {
  figure: ParticleOrb[]
  /** Rest-pose slot (loosened winning figure). Not an anonymous free-float cloud. */
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

function mixOrbs(figure: ParticleOrb[], rest: ParticleOrb[] | undefined, morph: number): ParticleOrb[] {
  const m = lifecycleMorphBlend(morph)
  if (!rest || rest.length === 0 || m >= 0.999) return figure
  if (m <= 0.001) return rest
  const n = Math.min(figure.length, rest.length)
  const out: ParticleOrb[] = new Array(n)
  for (let i = 0; i < n; i++) {
    const a = rest[i]
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

export type CloudAnatomy = {
  centroidX: number
  centroidY: number
  centroidZ: number
  width: number
  height: number
  depth: number
  goldMean: number
  radialRms: number
  upperShare: number
}

export function summarizeCloudAnatomy(orbs: ParticleOrb[]): CloudAnatomy {
  const n = Math.max(1, orbs.length)
  let cx = 0
  let cy = 0
  let cz = 0
  let gold = 0
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  let minZ = Number.POSITIVE_INFINITY
  let maxZ = Number.NEGATIVE_INFINITY
  for (const orb of orbs) {
    cx += orb.x
    cy += orb.y
    cz += orb.z
    gold += orb.gold
    minX = Math.min(minX, orb.x)
    maxX = Math.max(maxX, orb.x)
    minY = Math.min(minY, orb.y)
    maxY = Math.max(maxY, orb.y)
    minZ = Math.min(minZ, orb.z)
    maxZ = Math.max(maxZ, orb.z)
  }
  cx /= n
  cy /= n
  cz /= n
  let radial = 0
  let upper = 0
  for (const orb of orbs) {
    const dx = orb.x - cx
    const dy = orb.y - cy
    const dz = orb.z - cz
    radial += dx * dx + dy * dy + dz * dz
    if (orb.y > cy) upper += 1
  }
  return {
    centroidX: cx,
    centroidY: cy,
    centroidZ: cz,
    width: Math.max(0.001, maxX - minX),
    height: Math.max(0.001, maxY - minY),
    depth: Math.max(0.001, maxZ - minZ),
    goldMean: gold / n,
    radialRms: Math.sqrt(radial / n),
    upperShare: upper / n,
  }
}

export function meanOrbDisplacement(a: ParticleOrb[], b: ParticleOrb[]): number {
  const n = Math.min(a.length, b.length)
  if (n === 0) return Number.POSITIVE_INFINITY
  let sum = 0
  for (let i = 0; i < n; i++) {
    const dx = a[i].x - b[i].x
    const dy = a[i].y - b[i].y
    const dz = a[i].z - b[i].z
    sum += Math.hypot(dx, dy, dz)
  }
  return sum / n
}

export type RestIdentityReport = {
  readable: boolean
  failReasons: string[]
  restAnatomy: CloudAnatomy
  figureAnatomy: CloudAnatomy
  restToFigureDisplacement: number
  anonymousDisplacement: number
  silhouette: SilhouetteQualityReport
}

/**
 * Product rest identity: the displayed idle mix must stay a loosened winning
 * figure, not an anonymous sphere and not a chase of engaged 1.0.
 */
export function evaluateRestIdentity(input: {
  figure: ParticleOrb[]
  rest: ParticleOrb[]
  anonymous?: ParticleOrb[]
  morph?: number
  bloomStrength: number
  pointScale: number
  glow: number
  depthSoftness?: number
}): RestIdentityReport {
  const morph = input.morph ?? REST_TIGHTNESS
  const failReasons: string[] = []
  const displayed = mixOrbs(input.figure, input.rest, morph)
  const restAnatomy = summarizeCloudAnatomy(displayed)
  const figureAnatomy = summarizeCloudAnatomy(input.figure)
  const restToFigureDisplacement = meanOrbDisplacement(displayed, input.figure)
  const anonymousDisplacement = input.anonymous
    ? meanOrbDisplacement(displayed, input.anonymous)
    : Number.POSITIVE_INFINITY
  const silhouette = evaluateSilhouetteQuality({
    figure: input.figure,
    free: input.rest,
    morph,
    bloomStrength: input.bloomStrength,
    pointScale: input.pointScale,
    glow: input.glow,
    depthSoftness: input.depthSoftness,
  })
  if (!silhouette.readable) failReasons.push(...silhouette.failReasons)
  if (restSilhouetteOrAnonymous(morph) !== "silhouette") {
    failReasons.push("rest morph is an anonymous cloud")
  }
  if (Math.abs(restAnatomy.centroidY - figureAnatomy.centroidY) > 0.22) {
    failReasons.push(
      `rest centroid Y ${restAnatomy.centroidY.toFixed(3)} drifted from figure ${figureAnatomy.centroidY.toFixed(3)}`,
    )
  }
  if (Math.abs(restAnatomy.centroidX - figureAnatomy.centroidX) > 0.18) {
    failReasons.push("rest centroid X drifted off the figure")
  }
  const heightRatio = restAnatomy.height / figureAnatomy.height
  if (heightRatio < 0.78 || heightRatio > 1.35) {
    failReasons.push(`rest height ratio ${heightRatio.toFixed(3)} is not a loosened figure`)
  }
  if (restToFigureDisplacement > 0.55) {
    failReasons.push(`rest displacement ${restToFigureDisplacement.toFixed(3)} is a blob, not a bust`)
  }
  if (Number.isFinite(anonymousDisplacement) && restToFigureDisplacement > anonymousDisplacement * 0.55) {
    failReasons.push("rest is closer to an anonymous cloud than to the winning figure")
  }
  if (figureAnatomy.goldMean > 0.02 && restAnatomy.goldMean < figureAnatomy.goldMean * 0.2) {
    failReasons.push("rest gold collapsed (identity-hide of the amber core)")
  }
  if (figureAnatomy.goldMean > 0.02 && restAnatomy.goldMean >= figureAnatomy.goldMean * 0.98) {
    failReasons.push("rest gold chases engaged 1.0 (not loosened)")
  }
  if (restAnatomy.radialRms + 1e-6 < figureAnatomy.radialRms * 0.92) {
    failReasons.push("rest is tighter than the engaged figure")
  }
  const blend = lifecycleMorphBlend(morph)
  if (blend > 0.08) {
    failReasons.push(`rest blend ${blend.toFixed(3)} still mixes toward engaged`)
  }
  return {
    readable: failReasons.length === 0,
    failReasons,
    restAnatomy,
    figureAnatomy,
    restToFigureDisplacement,
    anonymousDisplacement,
    silhouette,
  }
}

export { REST_TIGHTNESS }
