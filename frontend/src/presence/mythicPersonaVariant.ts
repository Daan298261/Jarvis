export const MYTHIC_LIVE_B_AVATAR_ID = "mythic_live_b"
export const MYTHIC_PORTRAIT_A_AVATAR_ID = "mythic_portrait_a"
export const SETTINGS_CLOUD_SHAPE_ID = "settings_cloud"

export function mythicLiveVariantShapeId(shapeId: string | undefined | null): string {
  const base = (shapeId || "stormbird").trim() || "stormbird"
  if (base === SETTINGS_CLOUD_SHAPE_ID || base.endsWith("_b")) return base
  return `${base}_b`
}

export function usesMythicLiveVariantB(avatarId: string | undefined | null): boolean {
  return avatarId === MYTHIC_LIVE_B_AVATAR_ID
}
