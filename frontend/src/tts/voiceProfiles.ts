import { useEffect, useState } from "react"
import { api, fetchAudio } from "../api"

export const DEFAULT_VOICE_PROFILE_ID = "butler_original_v1"

const STORAGE_KEY = "jarvis.voice-profile.v1"
export const VOICE_PROFILE_CHANGED_EVENT = "jarvis:voice-profile-changed"

const FORBIDDEN_TOKENS = [
  "codsworth",
  "cortana",
  "ultron",
  "fallout",
  "halo",
  "marvel",
  "disney",
  "stephen russell",
]

export type VoiceProfile = {
  id: string
  archetype: string
  display_name: string
  available: boolean
  unavailable_reason?: string
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
      : typeof raw.install_hint === "string"
        ? raw.install_hint
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

  const butler = available.find((profile) => profile.id === DEFAULT_VOICE_PROFILE_ID)
  if (butler) return butler.id

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

export async function setActiveVoiceProfile(voiceProfileId: string): Promise<string | null> {
  const id = voiceProfileId.trim()
  if (!id) return null

  cacheActiveVoiceProfileId(id)
  announceActiveVoiceProfile(id)

  try {
    await api("/api/voice-profiles/active", {
      method: "PUT",
      body: JSON.stringify({ voice_profile_id: id }),
    })
  } catch {
    // D2: persist locally until backend accepts PUT /api/voice-profiles/active.
  }

  return id
}

async function requestPreviewBlob(profileId: string): Promise<Blob | null> {
  const encoded = encodeURIComponent(profileId)
  const attempts = [
    { path: `/api/voice-profiles/${encoded}/preview`, body: undefined },
    { path: "/api/voice-profiles/preview", body: JSON.stringify({ voice_profile_id: profileId }) },
  ]

  for (const attempt of attempts) {
    try {
      return await fetchAudio(attempt.path, {
        method: "POST",
        body: attempt.body,
      })
    } catch {
      // Try the next preview endpoint shape.
    }
  }
  return null
}

export async function previewVoiceProfile(profile: VoiceProfile): Promise<boolean> {
  if (!profile.available) return false

  try {
    const blob = await requestPreviewBlob(profile.id)
    if (!blob) return false
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    await new Promise<void>((resolve) => {
      const finish = () => {
        URL.revokeObjectURL(url)
        resolve()
      }
      audio.onended = finish
      audio.onerror = finish
      void audio.play().catch(finish)
    })
    return true
  } catch {
    return false
  }
}

export function getActiveVoiceProfileId(): string | null {
  return readActiveVoiceProfileBootstrap()
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
