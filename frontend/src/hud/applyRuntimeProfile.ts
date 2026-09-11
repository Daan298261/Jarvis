import {
  api,
  getRuntimeProfile,
  getSelectedRuntimePolicy,
  routeRuntime,
  selectLmStudioProfile,
  setSelectedRuntimeMode,
  setSelectedRuntimeProfileId,
  type RuntimeProfile,
} from "../api"

const BUILTIN_LOAD_PROFILES = new Set(["fast", "balanced", "quality", "expert"])

function resolveLoadProfile(profile: RuntimeProfile): string | null {
  if (profile.model_profile && BUILTIN_LOAD_PROFILES.has(profile.model_profile)) {
    return profile.model_profile
  }
  if (BUILTIN_LOAD_PROFILES.has(profile.name)) {
    return profile.name
  }
  return null
}

/** Mirror Model page + RuntimeProfiles force-select for one-click HUD hotswap. */
export async function applyRuntimeProfile(profileId: string): Promise<RuntimeProfile> {
  const profile = await getRuntimeProfile(profileId)
  const policy = getSelectedRuntimePolicy()
  const id = profile.id || profile.name

  setSelectedRuntimeProfileId(id)
  setSelectedRuntimeMode("force")
  window.dispatchEvent(new CustomEvent("jarvis:runtime-profile-changed", { detail: { id } }))

  try {
    await routeRuntime({ force_profile: id, policy })
  } catch {
    // Soft-fail routing; local selection still updated.
  }

  const loadName = resolveLoadProfile(profile)
  if (loadName) {
    try {
      await api("/api/model/load", { method: "POST", body: JSON.stringify({ profile: loadName }) })
    } catch {
      // Soft-fail model load (e.g. API down).
    }
  }

  return profile
}

/** RFC-0077 — bind LM Studio catalog row then force route/load (conversation stays client-side). */
export async function playLmStudioCatalogProfile(catalogProfileId: string): Promise<RuntimeProfile> {
  const runtime = await selectLmStudioProfile(catalogProfileId)
  const id = runtime.id || runtime.name
  return applyRuntimeProfile(id)
}
