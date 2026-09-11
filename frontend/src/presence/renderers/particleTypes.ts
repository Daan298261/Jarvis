/** One luminous orb sample in a presence shape cloud. */
export type ParticleOrb = {
  x: number
  y: number
  z: number
  /** 0 = cyan field, 1 = warm gold/brain accent */
  gold: number
  light: number
  /** 0 solid contour, ~0.4 dissolve, ~1 field drift, ~2 core pulse */
  flow: number
  size: number
}

export type PresenceShapeId = string

export type PresenceShapeFraming = {
  /** Bust yaw in radians (¾ profile ≈ 0.95). */
  yaw?: number
  position?: readonly [number, number, number]
}

export type PresenceShapeDefinition = {
  id: PresenceShapeId
  label: string
  /** Figure orbs that morph between shapes. */
  buildFigure: (density: number) => ParticleOrb[]
  /** Optional environment layer (mountains/HUD dust); swapped, not morph-lerped. */
  buildField?: (density: number) => ParticleOrb[]
  framing?: PresenceShapeFraming
}

export type PresenceShapeCatalog = ReadonlyMap<PresenceShapeId, PresenceShapeDefinition>
