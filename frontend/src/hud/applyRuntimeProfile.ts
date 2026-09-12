import {
  activateRuntimeProfile,
  getRuntimeProfile,
  selectLmStudioProfile,
  setSelectedRuntimeMode,
  setSelectedRuntimeProfileId,
  startHexStrike,
  stopHexStrike,
  type RuntimeProfile,
} from "../api"
import { isHexStrikeSuiteProfile } from "./hexstrikeSuite"

/** Mirror Model page + RuntimeProfiles force-select for one-click HUD hotswap. */
export async function applyRuntimeProfile(profileId: string): Promise<RuntimeProfile> {
  const id = profileId.trim()
  if (!id) {
    throw new Error("Runtime profile id is required.")
  }
  const profile = await getRuntimeProfile(id)

  setSelectedRuntimeProfileId(id)
  setSelectedRuntimeMode("force")
  window.dispatchEvent(new CustomEvent("jarvis:runtime-profile-changed", { detail: { id } }))

  if (isHexStrikeSuiteProfile(profile)) {
    await startHexStrike()
    return profile
  }

  try {
    await stopHexStrike()
  } catch {
    // Suite may already be idle.
  }

  const result = await activateRuntimeProfile(id)
  return result.profile || profile
}

/** RFC-0077 — bind LM Studio catalog row then force route/load (conversation stays client-side). */
export async function playLmStudioCatalogProfile(catalogProfileId: string): Promise<RuntimeProfile> {
  const runtime = await selectLmStudioProfile(catalogProfileId)
  const id = runtime.id || runtime.name
  return applyRuntimeProfile(id)
}
