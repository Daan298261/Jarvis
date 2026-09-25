export type ShellMode = "classic" | "hud"
export type PresenceMode = "none" | "neural" | "humanoid" | "particle_bust" | "galaxy"
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
  | "approval"
  | "error"

/** Optional named-persona colour, glow, and scale on the existing orb cloud. */
export type PersonaCloudVisual = {
  orbColor?: string
  accentColor?: string
  glow?: number
  animation?: number
  scale?: number
  /** Bounded renderer-wide orb size multiplier, independent of bust framing. */
  pointScale?: number
  /** 0 keeps depth contrast; 1 softens it for a flatter luminous look. */
  depthSoftness?: number
}

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
