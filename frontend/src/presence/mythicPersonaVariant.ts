export const MYTHIC_LIVING_AVATAR_ID = "mythic_living_b"
export const MYTHIC_LIVE_B_AVATAR_ID = "mythic_live_b"
export const MYTHIC_PORTRAIT_A_AVATAR_ID = "mythic_portrait_a"
export const SETTINGS_CLOUD_SHAPE_ID = "settings_cloud"

export function mythicLiveVariantShapeId(shapeId: string | undefined | null): string {
  const base = (shapeId || "stormbird").trim() || "stormbird"
  if (base === SETTINGS_CLOUD_SHAPE_ID || base.endsWith("_b")) return base
  return `${base}_b`
}

export function usesMythicLiveVariantB(avatarId: string | undefined | null): boolean {
  return avatarId === MYTHIC_LIVE_B_AVATAR_ID || avatarId === MYTHIC_LIVING_AVATAR_ID
}

export const MYTHIC_LEGACY_C_AVATAR_ID = "mythic_legacy_c"
export const MYTHIC_LEGACY_D_AVATAR_ID = "mythic_legacy_d"
export const LEGACY_HUMANOID_AVATAR_ID = "humanoid_legacy"

export const MYTHIC_AVATAR_CHOICES = [
  { id: MYTHIC_LIVING_AVATAR_ID, label: "Full body · living point cloud" },
  { id: MYTHIC_LIVE_B_AVATAR_ID, label: "Portrait · 3D live gaze" },
  { id: MYTHIC_PORTRAIT_A_AVATAR_ID, label: "Portrait · original artwork" },
] as const

export function mythicAvatarForSelection(avatarId: string): string {
  return MYTHIC_AVATAR_CHOICES.some(choice => choice.id === avatarId)
    ? avatarId : MYTHIC_LIVING_AVATAR_ID
}

export function legacyPersonaShapeId(avatarId: string, shapeId: string): string | undefined {
  if (avatarId === MYTHIC_LEGACY_C_AVATAR_ID) return shapeId.replace(/_b$/, "")
  if (avatarId === MYTHIC_LEGACY_D_AVATAR_ID) return mythicLiveVariantShapeId(shapeId)
  return undefined
}
