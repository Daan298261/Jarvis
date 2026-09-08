import { useEffect, useState } from "react"
import { api } from "../api"
import { getUiMode, setUiMode } from "../hud/uiMode"
import {
  DEFAULT_PRESENTATION_SETTINGS,
  type AttentionMode,
  type PresenceMode,
  type PresencePerformancePreset,
  type PresentationSettings,
  type ReducedMotionMode,
  type ShellMode,
} from "./presenceTypes"

const STORAGE_KEY = "jarvis.presentation.v3"
export const PRESENTATION_CHANGED_EVENT = "jarvis:presentation-changed"

const SHELLS = new Set<ShellMode>(["classic", "hud"])
const PRESENCES = new Set<PresenceMode>(["none", "neural", "humanoid"])
const PRESETS = new Set<PresencePerformancePreset>(["auto", "efficient", "balanced", "cinematic"])
const ATTENTION = new Set<AttentionMode>(["off", "pointer", "camera"])
const MOTION = new Set<ReducedMotionMode>(["system", "reduce", "full"])

function safeAvatarId(value: unknown): string {
  if (typeof value !== "string") return DEFAULT_PRESENTATION_SETTINGS.avatarId
  const trimmed = value.trim()
  if (!trimmed || trimmed.length > 80) return DEFAULT_PRESENTATION_SETTINGS.avatarId
  return trimmed
}

export function normalizePresentation(value: unknown): PresentationSettings {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {}
  const shellRaw = raw.shell
  const presenceRaw = raw.requestedPresence ?? raw.requested_presence
  const presetRaw = raw.performancePreset ?? raw.performance_preset
  const attentionRaw = raw.attentionMode ?? raw.attention_mode
  const motionRaw = raw.reducedMotion ?? raw.reduced_motion
  const avatarRaw = raw.avatarId ?? raw.avatar_id

  return {
    shell: typeof shellRaw === "string" && SHELLS.has(shellRaw as ShellMode)
      ? shellRaw as ShellMode
      : DEFAULT_PRESENTATION_SETTINGS.shell,
    requestedPresence: typeof presenceRaw === "string" && PRESENCES.has(presenceRaw as PresenceMode)
      ? presenceRaw as PresenceMode
      : DEFAULT_PRESENTATION_SETTINGS.requestedPresence,
    performancePreset: typeof presetRaw === "string" && PRESETS.has(presetRaw as PresencePerformancePreset)
      ? presetRaw as PresencePerformancePreset
      : DEFAULT_PRESENTATION_SETTINGS.performancePreset,
    attentionMode: typeof attentionRaw === "string" && ATTENTION.has(attentionRaw as AttentionMode)
      ? attentionRaw as AttentionMode
      : DEFAULT_PRESENTATION_SETTINGS.attentionMode,
    reducedMotion: typeof motionRaw === "string" && MOTION.has(motionRaw as ReducedMotionMode)
      ? motionRaw as ReducedMotionMode
      : DEFAULT_PRESENTATION_SETTINGS.reducedMotion,
    avatarId: safeAvatarId(avatarRaw),
  }
}

export function hasPresentationCache(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== null
  } catch {
    return false
  }
}

export function readPresentationBootstrap(): PresentationSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return normalizePresentation(JSON.parse(raw))
  } catch {
    // Fall through to the v2 UI-mode migration.
  }

  const oldMode = getUiMode()
  return {
    ...DEFAULT_PRESENTATION_SETTINGS,
    shell: oldMode,
    requestedPresence: oldMode === "classic" ? "none" : "neural",
  }
}

export function cachePresentation(settings: PresentationSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // Local cache is best-effort. Backend settings remain authoritative.
  }
  setUiMode(settings.shell)
}

function announce(settings: PresentationSettings): void {
  window.dispatchEvent(new CustomEvent<PresentationSettings>(PRESENTATION_CHANGED_EVENT, { detail: settings }))
}

export async function refreshPresentationFromBackend(): Promise<PresentationSettings> {
  const response = await api<any>("/api/settings")
  const settings = normalizePresentation(response?.presentation)
  cachePresentation(settings)
  announce(settings)
  return settings
}

export async function updatePresentation(
  patch: Partial<PresentationSettings>,
): Promise<PresentationSettings> {
  const current = readPresentationBootstrap()
  const requested = normalizePresentation({ ...current, ...patch })
  const body: Record<string, unknown> = {}

  if (patch.shell !== undefined) body.presentation_shell = requested.shell
  if (patch.requestedPresence !== undefined) body.presentation_requested_presence = requested.requestedPresence
  if (patch.performancePreset !== undefined) body.presentation_performance_preset = requested.performancePreset
  if (patch.attentionMode !== undefined) body.presentation_attention_mode = requested.attentionMode
  if (patch.reducedMotion !== undefined) body.presentation_reduced_motion = requested.reducedMotion
  if (patch.avatarId !== undefined) body.presentation_avatar_id = requested.avatarId

  const response = await api<any>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  })
  const settings = normalizePresentation(response?.presentation ?? requested)
  cachePresentation(settings)
  announce(settings)
  return settings
}

export async function initializePresentation(): Promise<PresentationSettings> {
  if (!hasPresentationCache()) {
    const migrated = readPresentationBootstrap()
    return updatePresentation({
      shell: migrated.shell,
      requestedPresence: migrated.requestedPresence,
    })
  }
  return refreshPresentationFromBackend()
}

export function usePresentationSettings(): PresentationSettings {
  const [settings, setSettings] = useState<PresentationSettings>(() => readPresentationBootstrap())

  useEffect(() => {
    const onChanged = (event: Event) => {
      const custom = event as CustomEvent<PresentationSettings>
      setSettings(normalizePresentation(custom.detail))
    }
    window.addEventListener(PRESENTATION_CHANGED_EVENT, onChanged)
    initializePresentation().catch(() => undefined)
    return () => window.removeEventListener(PRESENTATION_CHANGED_EVENT, onChanged)
  }, [])

  return settings
}
