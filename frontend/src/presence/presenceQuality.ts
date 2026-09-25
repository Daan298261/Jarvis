export const PRESENCE_QUALITY_DENSITIES = [0.6, 0.95, 1.15] as const
export type PresenceQualityTier = 0 | 1 | 2

/** Fit sampled shape bounds inside the stage frustum with a safe edge margin. */
export function normalizedPresenceFitScale(
  positions: ArrayLike<number>,
  aspect: number,
  fovDegrees: number,
  cameraDistance: number,
  yaw = 0,
  safeMargin = 0.88,
): number {
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  const c = Math.cos(yaw)
  const s = Math.sin(yaw)
  for (let i = 0; i < positions.length; i += 3) {
    const x = positions[i] * c + positions[i + 2] * s
    const y = positions[i + 1]
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
  }
  const height = Math.max(0.001, 2 * Math.max(Math.abs(minY), Math.abs(maxY)))
  const width = Math.max(0.001, 2 * Math.max(Math.abs(minX), Math.abs(maxX)))
  const visibleHeight = 2 * cameraDistance * Math.tan((fovDegrees * Math.PI) / 360)
  const visibleWidth = visibleHeight * Math.max(0.1, aspect)
  const margin = Number.isFinite(safeMargin) ? Math.max(0.5, Math.min(0.96, safeMargin)) : 0.88
  return Math.max(0.45, Math.min(1.35, margin * Math.min(visibleHeight / height, visibleWidth / width)))
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
