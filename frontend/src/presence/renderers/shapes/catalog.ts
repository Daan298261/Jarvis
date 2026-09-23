import type { ParticleOrb, PresenceShapeDefinition, PresenceShapeId } from "../particleTypes"
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
  if (orbs.length === count) return orbs.slice()
  const out: ParticleOrb[] = new Array(count)
  for (let i = 0; i < count; i++) {
    const t = i / count
    const idx = Math.min(orbs.length - 1, Math.floor(t * orbs.length))
    out[i] = orbs[idx]
  }
  return out
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
