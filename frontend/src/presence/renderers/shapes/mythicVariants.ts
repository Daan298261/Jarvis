import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { makeRng, pushOrb } from "./figureKit"

type VariantSpec = {
  seed: number
  crown: number
  beak?: boolean
  thirdEye?: boolean
  jawGold?: boolean
}

export const MYTHIC_B_SPECS: Record<string, VariantSpec> = {
  stormbird: { seed: 2411, crown: 15, beak: true },
  command_facet: { seed: 2417, crown: 6 },
  memory_rings: { seed: 2423, crown: 9, thirdEye: true },
  code_cube: { seed: 2437, crown: 8 },
  serpent_orbit: { seed: 2441, crown: 11 },
  twin_shield: { seed: 2447, crown: 7 },
  ocean_swell: { seed: 2459, crown: 12 },
  waveform_letters: { seed: 2467, crown: 10 },
  comet_trail: { seed: 2473, crown: 13 },
  eye_radar: { seed: 2477, crown: 5, thirdEye: true },
  breath_leaf: { seed: 2503, crown: 14 },
  star_social: { seed: 2521, crown: 8, thirdEye: true },
  forge_core: { seed: 2531, crown: 7, jawGold: true },
  opus_tide: { seed: 2539, crown: 16, thirdEye: true },
}

function buildStormbirdLiveFigure(density: number): ParticleOrb[] {
  const random = makeRng(2411)
  const orbs: ParticleOrb[] = []
  const stroke = (points: Array<[number, number, number?]>, count: number, gold: number, light: number) => {
    const total = Math.max(18, Math.round(count * density))
    for (let i = 0; i < total; i++) {
      const u = i / Math.max(1, total - 1)
      const segment = Math.min(points.length - 2, Math.floor(u * (points.length - 1)))
      const local = u * (points.length - 1) - segment
      const a = points[segment], b = points[segment + 1]
      pushOrb(orbs,
        a[0] + (b[0] - a[0]) * local + (random() - 0.5) * 0.018,
        a[1] + (b[1] - a[1]) * local + (random() - 0.5) * 0.018,
        (a[2] ?? 0.1) + ((b[2] ?? 0.1) - (a[2] ?? 0.1)) * local + (random() - 0.5) * 0.08,
        gold, light + random() * 0.45, 0.42, 1.22, density)
    }
  }

  for (const side of [-1, 1]) {
    // A hard avian brow and tapering cheek replace the round mask silhouette.
    stroke([[0, 1.02], [side * 0.48, 0.92], [side * 0.94, 0.58], [side * 0.66, 0.35],
      [side * 0.78, 0.08], [side * 0.48, -0.28], [side * 0.2, -0.8], [0, -1.02]], 1500, 0.05, 1.5)
    stroke([[0, 0.7, 0.24], [side * 0.34, 0.68, 0.28], [side * 0.7, 0.48, 0.22],
      [side * 0.35, 0.46, 0.31], [side * 0.08, 0.5, 0.3]], 680, 0.78, 1.75)

    // Long swept crown and cheek feathers make the stormbird readable at HUD scale.
    for (let feather = 0; feather < 11; feather++) {
      const rootX = side * (0.04 + feather * 0.055)
      const tipX = side * (0.62 + feather * 0.13)
      stroke([[rootX, 0.94 - feather * 0.012], [side * (0.28 + feather * 0.08), 1.18 + feather * 0.025],
        [tipX, 1.36 - feather * 0.012]], 175, feather % 3 === 0 ? 0.9 : 0.03, 1.38)
    }
    for (let feather = 0; feather < 9; feather++) {
      const y = 0.34 - feather * 0.115
      stroke([[side * 0.16, y + 0.12], [side * 0.62, y], [side * (1.06 + feather * 0.06), y - 0.12],
        [side * 0.54, y - 0.24]], 155, feather % 3 === 0 ? 0.84 : 0.025, 1.05)
    }

    // Narrow raptor eyes, aimed straight at the viewer.
    stroke([[side * 0.06, 0.6, 0.34], [side * 0.3, 0.66, 0.4], [side * 0.54, 0.57, 0.34],
      [side * 0.3, 0.52, 0.42], [side * 0.06, 0.6, 0.34]], 620, 1, 3.1)
  }

  // Long hooked golden beak and lightning scar form unmistakable central anchors.
  stroke([[0, 0.82, 0.36], [0.22, 0.34, 0.48], [0, -0.5, 0.56], [-0.22, 0.34, 0.48],
    [0, 0.82, 0.36]], 1250, 0.98, 2.15)
  stroke([[0, 0.16, 0.58], [0.18, -0.28, 0.5], [0.02, -0.68, 0.42], [-0.12, -0.34, 0.5]], 620, 0.94, 1.8)
  stroke([[-0.12, 1.08, 0.2], [0.08, 0.88, 0.28], [-0.02, 0.7, 0.32], [0.18, 0.5, 0.28]], 420, 1, 2.0)
  return orbs
}

function addDirectGazeMask(orbs: ParticleOrb[], density: number, spec: VariantSpec) {
  const random = makeRng(spec.seed)
  const surfaceCount = Math.max(900, Math.round(4600 * density))
  for (let i = 0; i < surfaceCount; i++) {
    const y = -1.05 + random() * 2.25
    const ny = (y - 0.06) / 1.18
    const halfWidth = 0.12 + 0.72 * Math.sqrt(Math.max(0, 1 - ny * ny))
    const x = (random() * 2 - 1) * halfWidth
    const nx = x / Math.max(0.12, halfWidth)
    const z = 0.02 + Math.sqrt(Math.max(0, 1 - nx * nx)) * 0.34 + (random() - 0.5) * 0.045
    const edge = Math.abs(nx) > 0.82 || Math.abs(ny) > 0.82
    pushOrb(orbs, x, y, z, spec.jawGold && y < -0.42 ? 0.7 : 0.035,
      edge ? 1.35 : 0.68, edge ? 0.18 : 0.06, 0.9 + random() * 0.72, density)
  }

  // Two luminous eyes are stable recognition anchors and face the camera.
  for (const side of [-1, 1]) {
    const eyeCount = Math.max(180, Math.round(760 * density))
    for (let i = 0; i < eyeCount; i++) {
      const angle = random() * Math.PI * 2
      const radius = Math.pow(random(), 1.7)
      pushOrb(orbs,
        side * (0.285 + Math.cos(angle) * radius * 0.12),
        0.38 + Math.sin(angle) * radius * 0.062,
        0.38 + random() * 0.055,
        1,
        3.1,
        2,
        1.45 + random() * 0.42,
        density,
      )
    }
  }

  const ridgeCount = Math.max(220, Math.round(980 * density))
  for (let i = 0; i < ridgeCount; i++) {
    const u = i / Math.max(1, ridgeCount - 1)
    const y = 0.72 - u * 1.28
    const hook = spec.beak ? Math.sin(u * Math.PI) * 0.22 : Math.sin(u * Math.PI) * 0.055
    const side = i % 2 === 0 ? -1 : 1
    pushOrb(orbs, side * hook, y, 0.4 + Math.sin(u * Math.PI) * 0.15,
      spec.beak ? 0.94 : 0.38, 1.55, 0.12, 1.1, density)
  }

  // A deterministic, persona-specific crown keeps the B silhouettes distinct.
  for (let ray = 0; ray < spec.crown; ray++) {
    const center = (ray - (spec.crown - 1) / 2) / Math.max(1, spec.crown - 1)
    const count = Math.max(70, Math.round(260 * density))
    for (let i = 0; i < count; i++) {
      const u = i / Math.max(1, count - 1)
      const sweep = center * (0.34 + u * (spec.beak ? 1.28 : 0.92))
      const wave = Math.sin(u * Math.PI) * (0.08 + (ray % 3) * 0.018)
      pushOrb(orbs, sweep + Math.sign(center || 1) * wave, 0.92 + u * (0.58 + Math.abs(center) * 0.35),
        -0.04 + u * 0.16, ray % 4 === 0 ? 0.88 : 0.05, 1.15, 0.34, 0.92, density)
    }
  }

  if (spec.thirdEye) {
    const count = Math.max(140, Math.round(520 * density))
    for (let i = 0; i < count; i++) {
      const angle = i / count * Math.PI * 2
      pushOrb(orbs, Math.cos(angle) * 0.09, 0.73 + Math.sin(angle) * 0.052, 0.43,
        0.95, 2.5, 2, 1.25, density)
    }
  }
}

/** Additive live B variant: the original motif becomes a halo around a volumetric, direct-gaze mask. */
export function createMythicBShape(base: PresenceShapeDefinition, spec: VariantSpec): PresenceShapeDefinition {
  return {
    id: `${base.id}_b`,
    label: `${base.label} B · live gaze`,
    buildFigure(density) {
      // Stormbird already owns a purpose-built frontal eagle mask. Keep its
      // hooked beak, feather crown, cheek wings and lightning markings intact
      // instead of burying them under the generic direct-gaze visage.
      if (base.id === "stormbird") {
        return buildStormbirdLiveFigure(density)
      }
      const halo = base.buildFigure(density).map((orb) => ({
        ...orb,
        x: orb.x * 0.9,
        y: orb.y * 0.78 - 0.03,
        z: orb.z * 0.62 - 0.28,
        light: orb.light * 0.68,
        flow: Math.max(0.24, Math.min(0.7, orb.flow)),
      }))
      addDirectGazeMask(halo, density, spec)
      return halo
    },
    buildField: base.buildField,
    framing: {
      yaw: 0,
      position: [0, -0.02, 0],
      fitMargin: Math.max(0.86, base.framing?.fitMargin ?? 0.88),
    },
    appearance: {
      ...base.appearance,
      depthSoftness: Math.min(0.2, base.appearance?.depthSoftness ?? 0.08),
      glow: Math.min(0.92, base.appearance?.glow ?? 0.84),
      bloomStrength: Math.min(0.3, base.appearance?.bloomStrength ?? 0.24),
    },
  }
}
