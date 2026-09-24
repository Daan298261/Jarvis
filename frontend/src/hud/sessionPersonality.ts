import { api } from "../api"

export type SessionMode = {
  id: string
  label: string
  hud_theme: string
  dialogue_preset?: string
  system_prefix_addendum?: string
  description?: string
  icon?: string
  accent?: string
  task_class_hint?: string
  preferred_profile?: string | null
}

const STORAGE_KEY = "jarvis.sessionMode"

export function applySessionTheme(mode: SessionMode | null): void {
  const theme = mode?.hud_theme || "core"
  document.documentElement.dataset.sessionMode = theme
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // ignore
  }
}

export async function refreshSessionPersonality(): Promise<SessionMode | null> {
  try {
    const payload = await api<{ active: SessionMode }>("/api/session-personality")
    applySessionTheme(payload.active)
    return payload.active
  } catch {
    return null
  }
}
