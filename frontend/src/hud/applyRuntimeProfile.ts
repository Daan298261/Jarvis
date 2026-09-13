import {
  activateRuntimeProfile,
  api,
  getRuntimeProfile,
  selectLmStudioProfile,
  setSelectedRuntimeMode,
  setSelectedRuntimeProfileId,
  startHexStrike,
  stopHexStrike,
  type RuntimeProfile,
} from "../api"
import { isHexStrikeSuiteProfile } from "./hexstrikeSuite"

type ModelPollSnapshot = {
  loaded?: boolean
  loading?: boolean
  last_error?: string
}

const MODEL_POLL_INTERVAL_MS = 500
/** Match managed llama.cpp start timeout so Play does not give up early. */
const MODEL_POLL_TIMEOUT_MS = 320_000

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

/** RFC-0077 — wait until /api/model reports ready or a load error (HUD Play / slots). */
export async function waitForModelLoaded(
  options: { timeoutMs?: number; intervalMs?: number } = {},
): Promise<ModelPollSnapshot> {
  const timeoutMs = options.timeoutMs ?? MODEL_POLL_TIMEOUT_MS
  const intervalMs = options.intervalMs ?? MODEL_POLL_INTERVAL_MS
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    const snap = await api<ModelPollSnapshot>("/api/model")
    const err = (snap.last_error || "").trim()
    if (err) {
      throw new Error(err)
    }
    if (snap.loaded && !snap.loading) {
      return snap
    }
    await sleep(intervalMs)
  }

  throw new Error("Model load timed out. Check runtime logs and try again.")
}

function syncRuntimeSelection(id: string): void {
  setSelectedRuntimeProfileId(id)
  setSelectedRuntimeMode("force")
  window.dispatchEvent(new CustomEvent("jarvis:runtime-profile-changed", { detail: { id } }))
}

/** Mirror Model page + RuntimeProfiles force-select for one-click HUD hotswap. */
export async function applyRuntimeProfile(profileId: string): Promise<RuntimeProfile> {
  const id = profileId.trim()
  if (!id) {
    throw new Error("Runtime profile id is required.")
  }
  const profile = await getRuntimeProfile(id)

  syncRuntimeSelection(id)

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
  await waitForModelLoaded()
  return result.profile || profile
}

/** RFC-0077 — bind LM Studio catalog row then force route/load (conversation stays client-side). */
export async function playLmStudioCatalogProfile(catalogProfileId: string): Promise<RuntimeProfile> {
  const runtime = await selectLmStudioProfile(catalogProfileId)
  const id = runtime.id || runtime.name
  syncRuntimeSelection(id)
  await waitForModelLoaded()
  return runtime
}
