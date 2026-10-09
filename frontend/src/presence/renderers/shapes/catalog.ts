import type { ParticleOrb, PresenceShapeDefinition, PresenceShapeId } from "../particleTypes"
import { makeRng } from "./figureKit"
import { humanoidBustShape } from "./humanoidBust"
import { energyCoreShape } from "./energyCore"
import { hexAegisShape } from "./hexAegis"
import { stormbirdShape } from "./stormbird"
import { commandFacetShape } from "./commandFacet"
import { memoryRingsShape } from "./memoryRings"
import { codeCubeShape } from "./codeCube"
import { serpentOrbitShape } from "./serpentOrbit"
import { twinShieldShape } from "./twinShield"
import { oceanSwellShape } from "./oceanSwell"
import { waveformLettersShape } from "./waveformLetters"
import { cometTrailShape } from "./cometTrail"
import { eyeRadarShape } from "./eyeRadar"
import { breathLeafShape } from "./breathLeaf"
import { starSocialShape } from "./starSocial"
import { forgeCoreShape } from "./forgeCore"
import { opusTideShape } from "./opusTide"
import { settingsCloudShape } from "./settingsCloud"
import { createMythicBShape, MYTHIC_B_SPECS } from "./mythicVariants"

export const DEFAULT_PRESENCE_SHAPE_ID: PresenceShapeId = "humanoid_bust"

/** Built-in + RFC-0137 roster ids — custom UI must never overwrite these. */
export const PROTECTED_PRESENCE_SHAPE_IDS = new Set<string>([
  "humanoid_bust",
  "energy_core",
  "hex_aegis",
  "stormbird",
  "command_facet",
  "memory_rings",
  "code_cube",
  "serpent_orbit",
  "twin_shield",
  "ocean_swell",
  "waveform_letters",
  "comet_trail",
  "eye_radar",
  "breath_leaf",
  "star_social",
  "forge_core",
  "opus_tide",
  "settings_cloud",
  ...Object.keys(MYTHIC_B_SPECS).map((id) => `${id}_b`),
])

const registry = new Map<PresenceShapeId, PresenceShapeDefinition>()

/** Register or replace a morphable presence shape. Catalog is intentionally expandable. */
export function registerPresenceShape(definition: PresenceShapeDefinition): void {
  if (!definition.id.trim()) throw new Error("Presence shape id must be non-empty")
  registry.set(definition.id, definition)
}

/**
 * Register a custom / preview presence shape.
 * Refuses protected built-in and roster ids (RFC-0138 — no overwrite path).
 */
export function registerCustomPresenceShape(definition: PresenceShapeDefinition): void {
  const id = definition.id.trim()
  if (!id) throw new Error("Presence shape id must be non-empty")
  if (PROTECTED_PRESENCE_SHAPE_IDS.has(id)) {
    throw new Error(`cannot register protected shape id: ${id}`)
  }
  if (!id.startsWith("custom_ui_")) {
    throw new Error(`custom presence shape id must start with custom_ui_: ${id}`)
  }
  registry.set(id, definition)
}

export function unregisterPresenceShape(id: string): void {
  const key = (id || "").trim()
  if (!key || PROTECTED_PRESENCE_SHAPE_IDS.has(key)) return
  registry.delete(key)
}

export function hasPresenceShape(id: string | undefined | null): boolean {
  return Boolean(id && registry.has(id))
}

export function listPresenceShapes(): PresenceShapeDefinition[] {
  return [...registry.values()]
}

export function resolvePresenceShape(id: string | undefined | null): PresenceShapeDefinition {
  if (id && registry.has(id)) return registry.get(id)!
  return registry.get(DEFAULT_PRESENCE_SHAPE_ID) ?? humanoidBustShape
}

/** Map persisted avatarId → shape id. Unknown avatars fall back to the default bust. */
export function presenceShapeIdForAvatar(avatarId: string | undefined | null): PresenceShapeId {
  const key = (avatarId || "").trim()
  if (!key || key === "jarvis_base") return DEFAULT_PRESENCE_SHAPE_ID
  if (registry.has(key)) return key
  // Convention: avatar ids may use shape ids directly, or `shape:<id>`.
  if (key.startsWith("shape:")) {
    const shaped = key.slice("shape:".length)
    if (registry.has(shaped)) return shaped
  }
  return DEFAULT_PRESENCE_SHAPE_ID
}

export function resampleOrbs(orbs: ParticleOrb[], count: number): ParticleOrb[] {
  if (count <= 0) return []
  if (orbs.length === 0) {
    return Array.from({ length: count }, () => ({
      x: 0, y: 0, z: 0, gold: 0, light: 0.2, flow: 0, size: 1.4,
    }))
  }
  // Portraits arrive in raster order. Shuffle before sampling so reducing the
  // GPU draw range removes scattered dots rather than contiguous rows/bars.
  // A fixed seed gives a stable nested subset when density moves up or down.
  const random = makeRng(6901210)
  const shuffle = (points: ParticleOrb[]) => {
    for (let i = points.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1))
      ;[points[i], points[j]] = [points[j], points[i]]
    }
    return points
  }
  const shuffled = shuffle(orbs.slice())
  if (count <= shuffled.length) return shuffled.slice(0, count)
  // Existing clouds may need more GPU slots than authored samples. Scatter
  // the repeats too, so a sparse prefix never favours the first cycle.
  return shuffle(Array.from({ length: count }, (_, i) => shuffled[i % shuffled.length]))
}

// Built-in shapes. Additional shapes register at module load or at runtime.
registerPresenceShape(humanoidBustShape)
registerPresenceShape(energyCoreShape)
registerPresenceShape(hexAegisShape)
registerPresenceShape(stormbirdShape)
registerPresenceShape(commandFacetShape)
registerPresenceShape(memoryRingsShape)
registerPresenceShape(codeCubeShape)
registerPresenceShape(serpentOrbitShape)
registerPresenceShape(twinShieldShape)
registerPresenceShape(oceanSwellShape)
registerPresenceShape(waveformLettersShape)
registerPresenceShape(cometTrailShape)
registerPresenceShape(eyeRadarShape)
registerPresenceShape(breathLeafShape)
registerPresenceShape(starSocialShape)
registerPresenceShape(forgeCoreShape)
registerPresenceShape(opusTideShape)
registerPresenceShape(settingsCloudShape)

const mythicBases: PresenceShapeDefinition[] = [
  stormbirdShape,
  commandFacetShape,
  memoryRingsShape,
  codeCubeShape,
  serpentOrbitShape,
  twinShieldShape,
  oceanSwellShape,
  waveformLettersShape,
  cometTrailShape,
  eyeRadarShape,
  breathLeafShape,
  starSocialShape,
  forgeCoreShape,
  opusTideShape,
]

for (const base of mythicBases) {
  const spec = MYTHIC_B_SPECS[base.id]
  if (spec) registerPresenceShape(createMythicBShape(base, spec))
}
