export type ShellMode = "classic" | "hud"
export type PresenceMode = "none" | "neural" | "humanoid"
export type PresencePerformancePreset = "auto" | "efficient" | "balanced" | "cinematic"
export type AttentionMode = "off" | "pointer" | "camera"
export type ReducedMotionMode = "system" | "reduce" | "full"

export type PresentationSettings = {
  shell: ShellMode
  requestedPresence: PresenceMode
  performancePreset: PresencePerformancePreset
  attentionMode: AttentionMode
  reducedMotion: ReducedMotionMode
  avatarId: string
}

export type PresencePhase =
  | "offline"
  | "idle"
  | "listening"
  | "thinking"
  | "executing"
  | "speaking"
  | "waiting"
  | "alert"

export type PresenceAttention = {
  x: number
  y: number
  z?: number
  confidence: number
  source: "pointer" | "camera"
}

export type PresenceSnapshot = {
  phase: PresencePhase
  intensity: number
  connected: boolean
  activeTaskId?: string
  activeTaskLabel?: string
  runningTaskCount: number
  decisionCount: number
  systemDegraded: boolean
  audioLevel: number
  attention?: PresenceAttention
}

export type EffectivePresence = {
  requested: PresenceMode
  effective: PresenceMode
  fallbackReason?: "renderer_unavailable" | "unsupported" | "renderer_error"
}

export const DEFAULT_PRESENTATION_SETTINGS: PresentationSettings = {
  shell: "hud",
  requestedPresence: "neural",
  performancePreset: "auto",
  attentionMode: "pointer",
  reducedMotion: "system",
  avatarId: "jarvis_base",
}
