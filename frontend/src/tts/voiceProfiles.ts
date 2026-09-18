import { useEffect, useState } from "react"
import { api, fetchAudioWithMetadata, isApiError, type AudioResponse } from "../api"
import { stopChatTts } from "./chatTtsPlayer"

export const WINDOWS_NATURAL_VOICE_PROFILE_ID = "windows_natural_en_v1"
export const KOKORO_BUTLER_VOICE_PROFILE_ID = "butler_original_v1"
export const DEFAULT_VOICE_PROFILE_ID = KOKORO_BUTLER_VOICE_PROFILE_ID

const STORAGE_KEY = "jarvis.voice-profile.v1"
export const VOICE_PROFILE_CHANGED_EVENT = "jarvis:voice-profile-changed"
export const VOICE_PROFILE_SWITCHING_EVENT = "jarvis:voice-profile-switching"

let voiceProfileSwitching = false

export function isVoiceProfileSwitching(): boolean {
  return voiceProfileSwitching
}

function announceVoiceProfileSwitching(switching: boolean): void {
  voiceProfileSwitching = switching
  window.dispatchEvent(new CustomEvent<boolean>(VOICE_PROFILE_SWITCHING_EVENT, { detail: switching }))
}

const FORBIDDEN_TOKENS = [
  "codsworth",
  "cortana",
  "ultron",
  "fallout",
  "halo",
  "marvel",
  "disney",
  "stephen russell",
  "iron man",
  "tony stark",
  "jarvis_marvel",
]

export type VoiceProfile = {
  id: string
  archetype: string
  display_name: string
  available: boolean
  unavailable_reason?: string
  install_hint?: string
  sample_utterance?: string
}

export type VoiceProfileCatalog = {
  profiles: VoiceProfile[]
  active_voice_profile_id: string | null
  apiAvailable: boolean
  loadMessage?: string
}

function containsForbiddenToken(value: string): boolean {
  const lower = value.toLowerCase()
  return FORBIDDEN_TOKENS.some((token) => lower.includes(token))
}

function formatArchetypeLabel(archetype: string): string {
  const words = archetype
    .replace(/[_-]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  if (!words.length) return "Original voice"
  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ")
}

export function sanitizeVoiceProfile(raw: Record<string, unknown>): VoiceProfile | null {
  const id = typeof raw.id === "string" ? raw.id.trim() : ""
  if (!id || containsForbiddenToken(id)) return null

  const archetype = typeof raw.archetype === "string" ? raw.archetype.trim() : ""
  const displayRaw = typeof raw.display_name === "string" ? raw.display_name.trim() : ""
  const display_name = displayRaw && !containsForbiddenToken(displayRaw)
    ? displayRaw
    : `${formatArchetypeLabel(archetype || id)} (original)`

  const available = raw.available !== false && raw.unavailable !== true
  const unavailable_reason = typeof raw.unavailable_reason === "string"
    ? raw.unavailable_reason
    : typeof raw.unavailableReason === "string"
      ? raw.unavailableReason
      : undefined
  const install_hint = typeof raw.install_hint === "string"
    ? raw.install_hint
    : typeof raw.installHint === "string"
      ? raw.installHint
      : undefined

  const sample_utterance = typeof raw.sample_utterance === "string"
    ? raw.sample_utterance
    : typeof raw.sampleUtterance === "string"
      ? raw.sampleUtterance
      : undefined

  return {
    id,
    archetype: archetype || "original",
    display_name,
    available,
    unavailable_reason,
    install_hint,
    sample_utterance,
  }
}

function normalizeCatalogPayload(data: unknown): { profiles: VoiceProfile[]; activeId: string | null } {
  const raw = data && typeof data === "object" ? data as Record<string, unknown> : {}
  const list = Array.isArray(data)
    ? data
    : Array.isArray(raw.profiles)
      ? raw.profiles
      : Array.isArray(raw.items)
        ? raw.items
        : []

  const profiles = list
    .map((item) => sanitizeVoiceProfile(item && typeof item === "object" ? item as Record<string, unknown> : {}))
    .filter((profile): profile is VoiceProfile => profile !== null)

  const activeRaw = raw.active_voice_profile_id
    ?? raw.activeVoiceProfileId
    ?? raw.active_id
    ?? raw.activeId
    ?? raw.active

  const activeId = typeof activeRaw === "string" && activeRaw.trim() ? activeRaw.trim() : null
  return { profiles, activeId }
}

export function readActiveVoiceProfileBootstrap(): string | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed === "string" && parsed.trim()) return parsed.trim()
    if (parsed && typeof parsed.active_voice_profile_id === "string" && parsed.active_voice_profile_id.trim()) {
      return parsed.active_voice_profile_id.trim()
    }
  } catch {
    // Fall through.
  }
  return null
}

function cacheActiveVoiceProfileId(id: string | null): void {
  try {
    if (id) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ active_voice_profile_id: id }))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // Best-effort until backend persists selection.
  }
}

function announceActiveVoiceProfile(id: string | null): void {
  window.dispatchEvent(new CustomEvent<string | null>(VOICE_PROFILE_CHANGED_EVENT, { detail: id }))
}

function pickDefaultActiveId(profiles: VoiceProfile[], preferred: string | null): string | null {
  const available = profiles.filter((profile) => profile.available)
  if (!available.length) return preferred

  if (preferred && available.some((profile) => profile.id === preferred)) return preferred

  const butler = available.find((profile) => profile.id === KOKORO_BUTLER_VOICE_PROFILE_ID)
  if (butler) return butler.id

  const windowsSystem = available.find((profile) => profile.id === WINDOWS_NATURAL_VOICE_PROFILE_ID)
  if (windowsSystem) return windowsSystem.id

  return available[0]?.id ?? null
}

export async function loadVoiceProfileCatalog(): Promise<VoiceProfileCatalog> {
  const cachedActive = readActiveVoiceProfileBootstrap()

  try {
    const data = await api<unknown>("/api/voice-profiles")
    const { profiles, activeId } = normalizeCatalogPayload(data)
    const resolvedActive = pickDefaultActiveId(profiles, activeId ?? cachedActive)

    if (resolvedActive) {
      cacheActiveVoiceProfileId(resolvedActive)
      announceActiveVoiceProfile(resolvedActive)
    }

    return {
      profiles,
      active_voice_profile_id: resolvedActive,
      apiAvailable: true,
    }
  } catch {
    return {
      profiles: [],
      active_voice_profile_id: cachedActive,
      apiAvailable: false,
      loadMessage: "Voice profile catalog is not available yet. Speech still uses your system TTS until the backend catalog lands (RFC-0062 D2).",
    }
  }
}

export async function setActiveVoiceProfile(
  voiceProfileId: string,
  options?: { preview?: boolean },
): Promise<string | null> {
  const id = voiceProfileId.trim()
  if (!id) return null

  announceVoiceProfileSwitching(true)
  try {
    stopChatTts()

    try {
      await api("/api/voice-profiles/active", {
        method: "PUT",
        body: JSON.stringify({ voice_profile_id: id }),
      })
    } catch {
      // D2: persist locally until backend accepts PUT /api/voice-profiles/active.
    }

    cacheActiveVoiceProfileId(id)
    announceActiveVoiceProfile(id)

    if (options?.preview !== false) {
      await previewVoiceProfile({
        id,
        archetype: "original",
        display_name: id,
        available: true,
      })
    }

    return id
  } finally {
    announceVoiceProfileSwitching(false)
  }
}

export async function installVoiceProfile(profileId: string): Promise<{ installed: boolean; detail?: string }> {
  const id = profileId.trim()
  if (!id) return { installed: false, detail: "Voice profile id is required." }
  const result = await api<{ installed?: boolean; detail?: string }>(
    `/api/voice-profiles/${encodeURIComponent(id)}/install`,
    { method: "POST" },
  )
  return {
    installed: result.installed !== false,
    detail: result.detail,
  }
}

export type VoicePreviewResult = {
  ok: boolean
  engineId?: string
  profileId?: string
  modelId?: string
  voiceId?: string
  error?: string
  status?: number
}

async function requestPreviewAudio(profileId: string): Promise<AudioResponse> {
  const encoded = encodeURIComponent(profileId)
  const attempts = [
    { path: `/api/voice-profiles/${encoded}/preview`, body: undefined },
    { path: "/api/voice-profiles/preview", body: JSON.stringify({ voice_profile_id: profileId }) },
  ]

  for (const attempt of attempts) {
    try {
      return await fetchAudioWithMetadata(attempt.path, {
        method: "POST",
        body: attempt.body,
      })
    } catch (err: unknown) {
      if (!isApiError(err) || (err.status !== 404 && err.status !== 405)) throw err
    }
  }
  throw new Error("No compatible voice preview endpoint is available.")
}

export async function previewVoiceProfile(profile: VoiceProfile): Promise<VoicePreviewResult> {
  if (!profile.available) {
    return {
      ok: false,
      error: profile.install_hint || profile.unavailable_reason || "This voice is not available.",
    }
  }

  let url: string | null = null
  try {
    const result = await requestPreviewAudio(profile.id)
    url = URL.createObjectURL(result.blob)
    const audio = new Audio(url)
    await new Promise<void>((resolve, reject) => {
      audio.onended = () => resolve()
      audio.onerror = () => reject(new Error("Preview audio was generated, but this client could not play the WAV."))
      void audio.play().catch(() => reject(new Error("Preview audio was generated, but this client could not play the WAV.")))
    })
    return {
      ok: true,
      engineId: result.engineId || undefined,
      profileId: result.profileId || undefined,
      modelId: result.modelId || undefined,
      voiceId: result.voiceId || undefined,
    }
  } catch (err: unknown) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Voice preview failed.",
      status: isApiError(err) ? err.status : undefined,
    }
  } finally {
    if (url) URL.revokeObjectURL(url)
  }
}

export function getActiveVoiceProfileId(): string | null {
  return readActiveVoiceProfileBootstrap()
}

export function useVoiceProfileSwitching(): boolean {
  const [switching, setSwitching] = useState(() => voiceProfileSwitching)

  useEffect(() => {
    const onSwitching = (event: Event) => {
      const custom = event as CustomEvent<boolean>
      setSwitching(Boolean(custom.detail))
    }
    window.addEventListener(VOICE_PROFILE_SWITCHING_EVENT, onSwitching)
    return () => window.removeEventListener(VOICE_PROFILE_SWITCHING_EVENT, onSwitching)
  }, [])

  return switching
}

export function useActiveVoiceProfileId(): string | null {
  const [activeId, setActiveId] = useState<string | null>(() => readActiveVoiceProfileBootstrap())

  useEffect(() => {
    const onChanged = (event: Event) => {
      const custom = event as CustomEvent<string | null>
      setActiveId(custom.detail)
    }
    window.addEventListener(VOICE_PROFILE_CHANGED_EVENT, onChanged)
    loadVoiceProfileCatalog()
      .then((catalog) => setActiveId(catalog.active_voice_profile_id))
      .catch(() => undefined)
    return () => window.removeEventListener(VOICE_PROFILE_CHANGED_EVENT, onChanged)
  }, [])

  return activeId
}
