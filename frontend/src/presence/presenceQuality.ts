export const PRESENCE_QUALITY_DENSITIES = [0.6, 0.95, 1.15] as const
export type PresenceQualityTier = 0 | 1 | 2

/**
 * Fallback bust yaw when a shape omits `framing.yaw`.
 * Fit measurement and stage rotation must share this value (RFC-0194 harden).
 */
export const PRESENCE_DEFAULT_FRAMING_YAW = 0.06

/** AABB fit: scale into the frustum plus geometric center for framing offset. */
export type PresenceFitFrame = {
  scale: number
  /** Geometric center X in the yaw frame (after Y-rotation used for fit). */
  centerX: number
  /** Geometric center Y (yaw-invariant). */
  centerY: number
  /** Geometric center Z in the yaw frame (after Y-rotation used for fit). */
  centerZ: number
}

export type PresenceFitYawFrameOffset = {
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

/**
 * Fit sampled shape bounds inside the stage frustum with a safe edge margin.
 * Uses AABB span (not origin-symmetric extent) so off-center busts are not
 * over-shrunk, and returns the geometric center in the yaw frame for stage
 * offset (RFC-0194).
 */
export function normalizedPresenceFitScale(
  positions: ArrayLike<number>,
  aspect: number,
  fovDegrees: number,
  cameraDistance: number,
  yaw = 0,
  safeMargin = 0.88,
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
    return { scale: 1, centerX: 0, centerY: 0, centerZ: 0 }
  }
  const height = Math.max(0.001, maxY - minY)
  const width = Math.max(0.001, maxX - minX)
  const centerX = (minX + maxX) * 0.5
  const centerY = (minY + maxY) * 0.5
  const centerZ = (minZ + maxZ) * 0.5
  const visibleHeight = 2 * cameraDistance * Math.tan((fovDegrees * Math.PI) / 360)
  const visibleWidth = visibleHeight * Math.max(0.1, aspect)
  const margin = Number.isFinite(safeMargin) ? Math.max(0.5, Math.min(0.96, safeMargin)) : 0.88
  const scale = Math.max(
    0.45,
    Math.min(1.35, margin * Math.min(visibleHeight / height, visibleWidth / width)),
  )
  return { scale, centerX, centerY, centerZ }
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
