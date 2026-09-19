import { api } from "../api"

export type SessionPersonalityId = "default" | "coding" | "research" | "concise"

export type SessionPersonalitySummary = {
  id: SessionPersonalityId
  display_name: string
  hud_theme: string
  tts_voice_hint?: string | null
  active?: boolean
}

export type SessionPersonalityState = {
  active_id: SessionPersonalityId
  display_name: string
  hud_theme: string
  personalities: SessionPersonalitySummary[]
}

const STORAGE_KEY = "jarvis_session_personality"

export function applySessionPersonalityDom(hudTheme: string, activeId: SessionPersonalityId): void {
  const theme = hudTheme || activeId || "default"
  document.documentElement.dataset.personality = theme
  const root = document.getElementById("root")
  if (root) root.dataset.personality = theme
}

export function cacheSessionPersonality(state: SessionPersonalityState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ active_id: state.active_id, hud_theme: state.hud_theme }))
  } catch {
    // ignore
  }
  applySessionPersonalityDom(state.hud_theme, state.active_id)
}

export function readSessionPersonalityBootstrap(): SessionPersonalityId {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return "default"
    const parsed = JSON.parse(raw) as { active_id?: string }
    const id = (parsed.active_id || "default").toLowerCase()
    if (id === "coding" || id === "research" || id === "concise" || id === "default") return id
  } catch {
    // ignore
  }
  return "default"
}

export async function fetchSessionPersonality(): Promise<SessionPersonalityState> {
  const payload = await api<SessionPersonalityState>("/api/personality")
  cacheSessionPersonality(payload)
  return payload
}

export async function selectSessionPersonality(personalityId: SessionPersonalityId): Promise<SessionPersonalityState> {
  const payload = await api<SessionPersonalityState>("/api/personality", {
    method: "POST",
    body: JSON.stringify({ personality_id: personalityId }),
  })
  cacheSessionPersonality(payload)
  return payload
}
