/** One luminous orb sample in a presence shape cloud. */
export type ParticleOrb = {
  x: number
  y: number
  z: number
  /** 0 = cyan field, 1 = warm gold/brain accent */
  gold: number
  light: number
  /** Negative values reserve solid living-bird chest/wing articulation.
   * 0 solid contour, ~0.4 dissolve, ~1 field drift, ~2 core pulse */
  flow: number
  size: number
  /** Linear RGB and authored-colour weight; absent uses the persona palette. */
  color?: readonly [number, number, number, number]
}

export type PresenceShapeId = string

/** RFC-0069 / RFC-0195 — crown, chin, and motif AABB consumed by fit + look-at. */
export type PresenceShapeLandmarks = {
  /** Highest silhouette Y (crown / top of motif). */
  crown: number
  /** Lowest silhouette Y (chin / base of motif). */
  chin: number
  /** Motif AABB in local space (hex rings, gold core, signature bounds). */
  motifBounds: {
    minX: number
    maxX: number
    minY: number
    maxY: number
    minZ: number
    maxZ: number
  }
}

export type PresenceShapeFraming = {
  /** Bust yaw in radians (¾ profile ≈ 0.95). */
  yaw?: number
  position?: readonly [number, number, number]
  /** Fraction of the stage viewport reserved for the projected shape (0.5–0.96). */
  fitMargin?: number
  /** Intentional lower-body crop for a presence emerging from the window edge. */
  cropBelow?: number
  /**
   * Identity landmarks for AABB + camera look-at (RFC-0195 / RFC-0069 amend).
   * Missing fields are derived from figure samples at fit time.
   */
  landmarks?: Partial<PresenceShapeLandmarks>
}

/** Shared shader appearance values; geometry remains owned by each shape. */
export type DotAppearanceProfile = {
  /** Artwork exposure calibrated to the humanoid; applies only to authored RGB. */
  portraitExposure?: number
  pointScale?: number
  depthSoftness?: number
  /** Glow / emission multiplier. Capped so bloom cannot wash motif edges. */
  glow?: number
  /** Bloom strength hint; resolved through silhouette-safe caps (RFC-0178 / 0195). */
  bloomStrength?: number
}

export type PresenceShapeDefinition = {
  id: PresenceShapeId
  label: string
  /** Figure orbs that morph between shapes. */
  buildFigure: (density: number) => ParticleOrb[]
  /** Optional environment layer (mountains/HUD dust); swapped, not morph-lerped. */
  buildField?: (density: number) => ParticleOrb[]
  framing?: PresenceShapeFraming
  appearance?: DotAppearanceProfile
}

export type PresenceShapeCatalog = ReadonlyMap<PresenceShapeId, PresenceShapeDefinition>
