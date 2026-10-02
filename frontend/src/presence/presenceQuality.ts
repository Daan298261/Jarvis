import type { PresencePerformancePreset } from "./presenceTypes"
import type {
  DotAppearanceProfile,
  ParticleOrb,
  PresenceShapeLandmarks,
} from "./renderers/particleTypes"

export const PRESENCE_QUALITY_DENSITIES = [0.6, 0.95, 1.15] as const
export type PresenceQualityTier = 0 | 1 | 2

/**
 * Fallback bust yaw when a shape omits `framing.yaw`.
 * Fit measurement and stage rotation must share this value (RFC-0194 harden).
 */
export const PRESENCE_DEFAULT_FRAMING_YAW = 0.06

/**
 * RFC-0195 Decision 2 / RFC-0178 — bloom, emission, and point scale caps so
 * edge contrast survives. Lowest auto tier may bypass bloom; the silhouette
 * must remain the silhouette, not a slab.
 */
export const PRESENCE_BLOOM_STRENGTH_MAX = 0.52
export const PRESENCE_BLOOM_RADIUS = 0.2
export const PRESENCE_BLOOM_THRESHOLD = 0.86
export const PRESENCE_BLOOM_STRENGTH_REST = 0.38
export const PRESENCE_POINT_SCALE_MIN = 0.5
export const PRESENCE_POINT_SCALE_MAX = 1.22
export const PRESENCE_GLOW_MIN = 0.35
export const PRESENCE_GLOW_MAX = 1.05
export const PRESENCE_DEPTH_SOFTNESS_MAX = 0.55
/** Occupied cells above this intensity count as washed-out (Mestor-slab fail). */
export const PRESENCE_OVEREXPOSURE_RATIO_MAX = 0.46
/** Mean edge vs interior contrast that a stranger needs to name the silhouette. */
export const PRESENCE_EDGE_CONTRAST_MIN = 0.14
/** Gold/motif ring occupancy vs the interstitial fill (hex rings vs disk). */
export const PRESENCE_MOTIF_CONTRAST_MIN = 0.08
/** Near-white accent luminance that would bloom motif rings into a slab. */
export const PRESENCE_ACCENT_LUMA_MAX = 0.82

/** AABB fit: scale into the frustum plus geometric center for framing offset. */
export type PresenceFitFrame = {
  scale: number
  /** Geometric center X in the yaw frame (after Y-rotation used for fit). */
  centerX: number
  /** Geometric center Y (yaw-invariant). */
  centerY: number
  /** Geometric center Z in the yaw frame (after Y-rotation used for fit). */
  centerZ: number
  /** Crown Y in the yaw frame (landmark or AABB max Y). */
  crownY: number
  /** Chin Y in the yaw frame (landmark or AABB min Y). */
  chinY: number
}

export type PresenceFitYawFrameOffset = {
  x: number
  y: number
  z: number
}

export type PresenceLookAt = {
  x: number
  y: number
  z: number
}

/**
 * Parent-space translation that cancels a yaw-frame AABB center under Three.js
 * `T * R_yaw * S` (position after rotate). Centers from
 * {@link normalizedPresenceFitScale} are already in that yaw frame, so the
 * offset stays in the same frame — do not treat `centerX` as pre-rotate local X.
 */
export function presenceFitYawFrameOffset(
  fit: Pick<PresenceFitFrame, "centerX" | "centerY" | "centerZ">,
  scale: number,
): PresenceFitYawFrameOffset {
  const s = Number.isFinite(scale) ? scale : 1
  return {
    x: -fit.centerX * s,
    y: -fit.centerY * s,
    z: -fit.centerZ * s,
  }
}

function yawRotate(x: number, z: number, yaw: number): { x: number; z: number } {
  const c = Math.cos(yaw)
  const s = Math.sin(yaw)
  return { x: x * c + z * s, z: -x * s + z * c }
}

export function landmarksFromPositions(
  positions: ArrayLike<number>,
  yaw = 0,
): PresenceShapeLandmarks {
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  let minZ = Number.POSITIVE_INFINITY
  let maxZ = Number.NEGATIVE_INFINITY
  for (let i = 0; i < positions.length; i += 3) {
    const rotated = yawRotate(positions[i], positions[i + 2], yaw)
    const y = positions[i + 1]
    minX = Math.min(minX, rotated.x)
    maxX = Math.max(maxX, rotated.x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
    minZ = Math.min(minZ, rotated.z)
    maxZ = Math.max(maxZ, rotated.z)
  }
  if (!Number.isFinite(minX)) {
    return {
      crown: 1,
      chin: -1,
      motifBounds: { minX: -1, maxX: 1, minY: -1, maxY: 1, minZ: -1, maxZ: 1 },
    }
  }
  return {
    crown: maxY,
    chin: minY,
    motifBounds: { minX, maxX, minY, maxY, minZ, maxZ },
  }
}

export function landmarksFromOrbs(orbs: ParticleOrb[], yaw = 0): PresenceShapeLandmarks {
  const positions = new Float32Array(orbs.length * 3)
  for (let i = 0; i < orbs.length; i++) {
    positions[i * 3] = orbs[i].x
    positions[i * 3 + 1] = orbs[i].y
    positions[i * 3 + 2] = orbs[i].z
  }
  return landmarksFromPositions(positions, yaw)
}

function yawFrameBounds(
  bounds: PresenceShapeLandmarks["motifBounds"],
  yaw: number,
): PresenceShapeLandmarks["motifBounds"] {
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minZ = Number.POSITIVE_INFINITY
  let maxZ = Number.NEGATIVE_INFINITY
  const corners: Array<[number, number]> = [
    [bounds.minX, bounds.minZ],
    [bounds.minX, bounds.maxZ],
    [bounds.maxX, bounds.minZ],
    [bounds.maxX, bounds.maxZ],
  ]
  for (const [lx, lz] of corners) {
    const rotated = yawRotate(lx, lz, yaw)
    minX = Math.min(minX, rotated.x)
    maxX = Math.max(maxX, rotated.x)
    minZ = Math.min(minZ, rotated.z)
    maxZ = Math.max(maxZ, rotated.z)
  }
  return {
    minX,
    maxX,
    minY: bounds.minY,
    maxY: bounds.maxY,
    minZ,
    maxZ,
  }
}

export function resolveShapeLandmarks(
  declared: Partial<PresenceShapeLandmarks> | undefined,
  positions: ArrayLike<number>,
  yaw = 0,
): PresenceShapeLandmarks {
  const derived = landmarksFromPositions(positions, yaw)
  const motif = declared?.motifBounds
    ? yawFrameBounds(declared.motifBounds, yaw)
    : derived.motifBounds
  return {
    crown: typeof declared?.crown === "number" && Number.isFinite(declared.crown)
      ? declared.crown
      : derived.crown,
    chin: typeof declared?.chin === "number" && Number.isFinite(declared.chin)
      ? declared.chin
      : derived.chin,
    motifBounds: motif,
  }
}

function expandAabbWithLandmarks(
  box: { minX: number; maxX: number; minY: number; maxY: number; minZ: number; maxZ: number },
  landmarks: PresenceShapeLandmarks,
): void {
  box.minY = Math.min(box.minY, landmarks.chin, landmarks.motifBounds.minY)
  box.maxY = Math.max(box.maxY, landmarks.crown, landmarks.motifBounds.maxY)
  box.minX = Math.min(box.minX, landmarks.motifBounds.minX)
  box.maxX = Math.max(box.maxX, landmarks.motifBounds.maxX)
  box.minZ = Math.min(box.minZ, landmarks.motifBounds.minZ)
  box.maxZ = Math.max(box.maxZ, landmarks.motifBounds.maxZ)
}

/**
 * After the yaw-frame offset, the silhouette geometric center (including
 * landmarks) sits on the camera look-at. Stage cameras look at origin.
 */
export function presenceLookAtFromFit(
  _fit: Pick<PresenceFitFrame, "centerX" | "centerY" | "centerZ">,
): PresenceLookAt {
  return { x: 0, y: 0, z: 0 }
}

/** Concatenate rest + engaged slots so AABB fit covers both poses (no rest crop). */
export function unionPresencePositions(
  rest: ArrayLike<number>,
  figure: ArrayLike<number>,
): Float32Array {
  const out = new Float32Array(rest.length + figure.length)
  out.set(rest, 0)
  out.set(figure, rest.length)
  return out
}

export type PresenceIdentityOnFrame = {
  minX: number
  maxX: number
  minY: number
  maxY: number
  crownY: number
  chinY: number
  visibleHalfW: number
  visibleHalfH: number
  onFrame: boolean
}

/**
 * After yaw-frame offset, rest/engaged landmarks must stay inside the camera
 * frustum. Used to catch rest-specific crop (RFC-0194 crop-protection at rest).
 */
export function identityOnLookAtAfterFit(input: {
  positions: ArrayLike<number>
  fit: PresenceFitFrame
  fovDegrees: number
  cameraDistance: number
  yaw?: number
  aspect: number
  margin?: number
}): PresenceIdentityOnFrame {
  const yaw = input.yaw ?? 0
  const scale = input.fit.scale
  const offset = presenceFitYawFrameOffset(input.fit, scale)
  const c = Math.cos(yaw)
  const s = Math.sin(yaw)
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  const pos = input.positions
  for (let i = 0; i < pos.length; i += 3) {
    const lx = pos[i] * scale
    const ly = pos[i + 1] * scale
    const lz = pos[i + 2] * scale
    const x = offset.x + lx * c + lz * s
    const y = offset.y + ly
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
  }
  const visibleHeight = 2 * input.cameraDistance * Math.tan((input.fovDegrees * Math.PI) / 360)
  const visibleWidth = visibleHeight * Math.max(0.1, input.aspect)
  const pad = Number.isFinite(input.margin) ? Math.max(0.5, Math.min(0.98, input.margin!)) : 0.96
  const visibleHalfW = (visibleWidth * pad) / 2
  const visibleHalfH = (visibleHeight * pad) / 2
  const onFrame = Number.isFinite(minX)
    && minX >= -visibleHalfW - 0.02
    && maxX <= visibleHalfW + 0.02
    && minY >= -visibleHalfH - 0.02
    && maxY <= visibleHalfH + 0.02
  return {
    minX,
    maxX,
    minY,
    maxY,
    crownY: maxY,
    chinY: minY,
    visibleHalfW,
    visibleHalfH,
    onFrame,
  }
}

/**
 * Fit sampled shape bounds inside the stage frustum with a safe edge margin.
 * Uses AABB span (not origin-symmetric extent) so off-center busts are not
 * over-shrunk, and returns the geometric center in the yaw frame for stage
 * offset (RFC-0194). Landmarks expand the AABB so crown / chin / motif stay
 * on-frame under viewport-fill (RFC-0195 / RFC-0069).
 */
export function normalizedPresenceFitScale(
  positions: ArrayLike<number>,
  aspect: number,
  fovDegrees: number,
  cameraDistance: number,
  yaw = 0,
  safeMargin = 0.88,
  landmarks?: Partial<PresenceShapeLandmarks>,
): PresenceFitFrame {
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  let minZ = Number.POSITIVE_INFINITY
  let maxZ = Number.NEGATIVE_INFINITY
  const c = Math.cos(yaw)
  const s = Math.sin(yaw)
  for (let i = 0; i < positions.length; i += 3) {
    const lx = positions[i]
    const ly = positions[i + 1]
    const lz = positions[i + 2]
    // Same Y-rotation as Three.js Object3D.rotation.y (yaw frame).
    const x = lx * c + lz * s
    const z = -lx * s + lz * c
    const y = ly
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
    minZ = Math.min(minZ, z)
    maxZ = Math.max(maxZ, z)
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(minZ)) {
    return { scale: 1, centerX: 0, centerY: 0, centerZ: 0, crownY: 1, chinY: -1 }
  }
  const resolved = resolveShapeLandmarks(landmarks, positions, yaw)
  const box = { minX, maxX, minY, maxY, minZ, maxZ }
  expandAabbWithLandmarks(box, resolved)
  const height = Math.max(0.001, box.maxY - box.minY)
  const width = Math.max(0.001, box.maxX - box.minX)
  const centerX = (box.minX + box.maxX) * 0.5
  const centerY = (box.minY + box.maxY) * 0.5
  const centerZ = (box.minZ + box.maxZ) * 0.5
  const visibleHeight = 2 * cameraDistance * Math.tan((fovDegrees * Math.PI) / 360)
  const visibleWidth = visibleHeight * Math.max(0.1, aspect)
  const margin = Number.isFinite(safeMargin) ? Math.max(0.5, Math.min(0.96, safeMargin)) : 0.88
  const scale = Math.max(
    0.45,
    Math.min(1.35, margin * Math.min(visibleHeight / height, visibleWidth / width)),
  )
  return {
    scale,
    centerX,
    centerY,
    centerZ,
    crownY: resolved.crown,
    chinY: resolved.chin,
  }
}

function bounded(value: number | undefined, fallback: number, min: number, max: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(min, Math.min(max, value))
    : fallback
}

export type ResolvedDotAppearance = {
  pointScale: number
  depthSoftness: number
  glow: number
  bloomStrength: number
}

/**
 * Geometry stays on `buildFigure`. Profiles only tune palette-adjacent shader
 * knobs, and those knobs are capped so they cannot drop silhouette or motif
 * (RFC-0176 + RFC-0195).
 */
export function resolveDotAppearance(
  profile: DotAppearanceProfile | undefined,
  visual?: { pointScale?: number; depthSoftness?: number; glow?: number },
): ResolvedDotAppearance {
  const pointScale = bounded(
    visual?.pointScale,
    bounded(profile?.pointScale, 1, PRESENCE_POINT_SCALE_MIN, PRESENCE_POINT_SCALE_MAX),
    PRESENCE_POINT_SCALE_MIN,
    PRESENCE_POINT_SCALE_MAX,
  )
  const depthSoftness = bounded(
    visual?.depthSoftness,
    bounded(profile?.depthSoftness, 0, 0, PRESENCE_DEPTH_SOFTNESS_MAX),
    0,
    PRESENCE_DEPTH_SOFTNESS_MAX,
  )
  const glow = bounded(
    visual?.glow,
    bounded(profile?.glow, 1, PRESENCE_GLOW_MIN, PRESENCE_GLOW_MAX),
    PRESENCE_GLOW_MIN,
    PRESENCE_GLOW_MAX,
  )
  const bloomStrength = bounded(
    profile?.bloomStrength,
    Math.min(PRESENCE_BLOOM_STRENGTH_MAX, 0.32 + glow * 0.18),
    0,
    PRESENCE_BLOOM_STRENGTH_MAX,
  )
  return { pointScale, depthSoftness, glow, bloomStrength }
}

export type PresenceBloomPass = {
  enabled: boolean
  strength: number
  radius: number
  threshold: number
}

/**
 * Adaptive tiers may drop bloom under hysteresis (RFC-0178). They must not
 * flatten the figure into a slab to "save FPS" (RFC-0195).
 */
export function resolvePresenceBloom(input: {
  appearance: ResolvedDotAppearance
  performancePreset: PresencePerformancePreset
  autoTier: PresenceQualityTier
  rest: boolean
}): PresenceBloomPass {
  const lowestAuto = input.performancePreset === "auto" && input.autoTier === 0
  const efficient = input.performancePreset === "efficient"
  if (lowestAuto || efficient) {
    return {
      enabled: false,
      strength: 0,
      radius: PRESENCE_BLOOM_RADIUS,
      threshold: PRESENCE_BLOOM_THRESHOLD,
    }
  }
  const restCap = input.rest ? PRESENCE_BLOOM_STRENGTH_REST : PRESENCE_BLOOM_STRENGTH_MAX
  const strength = Math.min(restCap, input.appearance.bloomStrength)
  return {
    enabled: true,
    strength,
    radius: PRESENCE_BLOOM_RADIUS,
    threshold: PRESENCE_BLOOM_THRESHOLD,
  }
}

function parseCssHex(hex: string): { r: number; g: number; b: number } | null {
  const raw = hex.trim().replace(/^#/, "")
  if (!/^[0-9a-fA-F]{6}$/.test(raw) && !/^[0-9a-fA-F]{3}$/.test(raw)) return null
  const full = raw.length === 3
    ? raw.split("").map((ch) => ch + ch).join("")
    : raw
  return {
    r: Number.parseInt(full.slice(0, 2), 16) / 255,
    g: Number.parseInt(full.slice(2, 4), 16) / 255,
    b: Number.parseInt(full.slice(4, 6), 16) / 255,
  }
}

function luma(rgb: { r: number; g: number; b: number }): number {
  return 0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b
}

function toHex(rgb: { r: number; g: number; b: number }): string {
  const ch = (v: number) => Math.max(0, Math.min(255, Math.round(v * 255))).toString(16).padStart(2, "0")
  return `#${ch(rgb.r)}${ch(rgb.g)}${ch(rgb.b)}`
}

/**
 * Near-white persona accents (Mestor `#F8FAFC`) bloom hexagonal rings into a
 * slab. Pull luminance down so the motif keeps edge contrast.
 */
export function motifSafeAccentHex(accent: string | undefined, orb?: string): string {
  const parsed = accent ? parseCssHex(accent) : null
  if (!parsed) return accent || "#D4A017"
  if (luma(parsed) <= PRESENCE_ACCENT_LUMA_MAX) return accent!.startsWith("#") ? accent! : `#${accent}`
  const orbRgb = orb ? parseCssHex(orb) : null
  const cool = orbRgb
    ? {
      r: orbRgb.r * 0.35 + 0.45,
      g: orbRgb.g * 0.35 + 0.55,
      b: orbRgb.b * 0.25 + 0.72,
    }
    : { r: 0.48, g: 0.68, b: 0.86 }
  const mix = 0.42
  return toHex({
    r: parsed.r * mix + cool.r * (1 - mix),
    g: parsed.g * mix + cool.g * (1 - mix),
    b: parsed.b * mix + cool.b * (1 - mix),
  })
}

/** Auto quality controller with sustained frame-time thresholds and cooldown. */
export class AutoPresenceQuality {
  private tier: PresenceQualityTier = 1
  private averageMs = 16.67
  private slowMs = 0
  private fastMs = 0
  private changedAt = Number.NEGATIVE_INFINITY
  private lastTime: number | undefined

  get current(): PresenceQualityTier {
    return this.tier
  }

  get averageFrameTimeMs(): number {
    return this.averageMs
  }

  sample(timeMs: number, frameMs: number): PresenceQualityTier {
    const dt = this.lastTime === undefined ? 0 : Math.max(0, Math.min(100, timeMs - this.lastTime))
    this.lastTime = timeMs
    const sample = Number.isFinite(frameMs) ? Math.max(0, Math.min(100, frameMs)) : 16.67
    this.averageMs += (sample - this.averageMs) * (dt > 0 ? 1 - Math.exp(-dt / 450) : 0)
    this.slowMs = this.averageMs > 20 ? this.slowMs + dt : 0
    this.fastMs = this.averageMs < 17 ? this.fastMs + dt : 0
    if (timeMs - this.changedAt < 5000) return this.tier

    if (this.slowMs >= 2000 && this.tier > 0) {
      this.tier = (this.tier - 1) as PresenceQualityTier
      this.changedAt = timeMs
      this.slowMs = 0
      this.fastMs = 0
    } else if (this.fastMs >= 8000 && this.tier < 2) {
      this.tier = (this.tier + 1) as PresenceQualityTier
      this.changedAt = timeMs
      this.slowMs = 0
      this.fastMs = 0
    }
    return this.tier
  }
}
