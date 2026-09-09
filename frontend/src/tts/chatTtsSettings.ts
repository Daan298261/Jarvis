import { useEffect, useState } from "react"
import { api } from "../api"

export type TtsSettings = {
  speak_chat_replies: boolean
}

export const DEFAULT_TTS_SETTINGS: TtsSettings = {
  speak_chat_replies: true,
}

const STORAGE_KEY = "jarvis.tts.v1"
export const TTS_SETTINGS_CHANGED_EVENT = "jarvis:tts-settings-changed"

function normalizeTts(value: unknown): TtsSettings {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {}
  const speakRaw = raw.speak_chat_replies ?? raw.speakChatReplies
  return {
    speak_chat_replies: typeof speakRaw === "boolean" ? speakRaw : DEFAULT_TTS_SETTINGS.speak_chat_replies,
  }
}

export function readTtsBootstrap(): TtsSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return normalizeTts(JSON.parse(raw))
  } catch {
    // Fall through to defaults.
  }
  return DEFAULT_TTS_SETTINGS
}

function cacheTts(settings: TtsSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // Local cache is best-effort until backend persists tts.*.
  }
}

function announce(settings: TtsSettings): void {
  window.dispatchEvent(new CustomEvent<TtsSettings>(TTS_SETTINGS_CHANGED_EVENT, { detail: settings }))
}

export async function refreshTtsFromBackend(): Promise<TtsSettings> {
  const response = await api<any>("/api/settings")
  const fromApi = normalizeTts(response?.tts)
  const cached = readTtsBootstrap()
  const settings = response?.tts ? fromApi : cached
  cacheTts(settings)
  announce(settings)
  return settings
}

export async function updateTtsSettings(patch: Partial<TtsSettings>): Promise<TtsSettings> {
  const current = readTtsBootstrap()
  const next = normalizeTts({ ...current, ...patch })
  cacheTts(next)
  announce(next)

  // D1: backend will accept tts_speak_chat_replies on PUT /api/settings.
  if (patch.speak_chat_replies !== undefined) {
    api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ tts_speak_chat_replies: next.speak_chat_replies }),
    }).catch(() => undefined)
  }

  return next
}

export function useSpeakChatReplies(): [boolean, (enabled: boolean) => Promise<void>] {
  const [enabled, setEnabled] = useState(() => readTtsBootstrap().speak_chat_replies)

  useEffect(() => {
    const onChanged = (event: Event) => {
      const custom = event as CustomEvent<TtsSettings>
      setEnabled(normalizeTts(custom.detail).speak_chat_replies)
    }
    window.addEventListener(TTS_SETTINGS_CHANGED_EVENT, onChanged)
    refreshTtsFromBackend().catch(() => undefined)
    return () => window.removeEventListener(TTS_SETTINGS_CHANGED_EVENT, onChanged)
  }, [])

  const setSpeakChatReplies = async (next: boolean) => {
    const settings = await updateTtsSettings({ speak_chat_replies: next })
    setEnabled(settings.speak_chat_replies)
  }

  return [enabled, setSpeakChatReplies]
}
