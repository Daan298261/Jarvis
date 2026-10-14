import type { ParticleOrb } from "../particleTypes"

/** Mean linear light × sprite area of the production humanoid artwork. */
export const HUMANOID_PORTRAIT_ENERGY = 1.18

export function portraitSampleEnergy(points: ParticleOrb[]): number {
  if (!points.length) return 0
  let energy = 0
  for (const point of points) {
    const color = point.color
    if (!color) continue
    const luminance = color[0] * 0.2126 + color[1] * 0.7152 + color[2] * 0.0722
    energy += luminance * point.light * point.size * point.size * color[3]
  }
  return energy / points.length
}

/** One hue-preserving exposure for the whole portrait; retain authored shading. */
export function calibratedPortraitExposure(points: ParticleOrb[]): number {
  const energy = portraitSampleEnergy(points)
  if (!Number.isFinite(energy) || energy <= 0) return 1
  // Already bright portraits retain their authored light; only lift underlit art.
  return Math.max(1, Math.min(12, HUMANOID_PORTRAIT_ENERGY / energy))
}
