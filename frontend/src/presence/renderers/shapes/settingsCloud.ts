import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { makeRng, pushOrb } from "./figureKit"

/**
 * Full-stage working cloud used while a HUD settings panel is open. The
 * existing figure orbs morph here through the shared shape API; this is not a
 * bitmap, background swap, second canvas, or second particle system.
 */
export function buildSettingsCloudFigure(density: number): ParticleOrb[] {
  const random = makeRng(19502)
  const orbs: ParticleOrb[] = []
  const count = Math.max(1800, Math.round(18000 * density))
  for (let i = 0; i < count; i++) {
    const angle = random() * Math.PI * 2
    const elevation = Math.acos(random() * 2 - 1)
    const radius = Math.cbrt(random())
    const x = Math.sin(elevation) * Math.cos(angle) * radius * 2.65
    const y = Math.sin(elevation) * Math.sin(angle) * radius * 1.48
    const z = Math.cos(elevation) * radius * 0.72
    const edge = Math.max(0, radius - 0.7) / 0.3
    pushOrb(
      orbs,
      x,
      y,
      z,
      i % 29 === 0 ? 0.68 : 0.015,
      0.22 + (1 - edge) * 1.22,
      0.42 + random() * 0.24,
      0.82 + random() * 0.76,
      density,
    )
  }
  return orbs
}

export const settingsCloudShape: PresenceShapeDefinition = {
  id: "settings_cloud",
  label: "Settings particle cloud",
  buildFigure: buildSettingsCloudFigure,
  framing: { yaw: 0, position: [0, 0, 0], fitMargin: 0.97 },
  appearance: { pointScale: 0.88, depthSoftness: 0.18, glow: 0.72, bloomStrength: 0.2 },
}
