import type { ParticleOrb, PresenceShapeDefinition, PresenceShapeId } from "../particleTypes"
import { humanoidBustShape } from "./humanoidBust"
import { energyCoreShape } from "./energyCore"
import { hexAegisShape } from "./hexAegis"

export const DEFAULT_PRESENCE_SHAPE_ID: PresenceShapeId = "humanoid_bust"

const registry = new Map<PresenceShapeId, PresenceShapeDefinition>()

/** Register or replace a morphable presence shape. Catalog is intentionally expandable. */
export function registerPresenceShape(definition: PresenceShapeDefinition): void {
  if (!definition.id.trim()) throw new Error("Presence shape id must be non-empty")
  registry.set(definition.id, definition)
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
