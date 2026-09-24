import type { PresenceMode, PresencePhase } from "./presenceTypes"

/** Figure and field budgets stay at the pre-Galaxy scales. Stars are extra. */
export const FIGURE_BUDGET_SCALE = 82000
export const FIELD_BUDGET_SCALE = 15000
export const GALAXY_STAR_BUDGET_SCALE = 24000

const PRESENCE_MODES = ["none", "neural", "humanoid", "particle_bust", "galaxy"] as const

const GALAXY_PHASE: Record<PresencePhase, string> = {
  idle: "IDLE",
  waiting: "IDLE",
  thinking: "THINKING",
  listening: "LISTENING",
  speaking: "SPEAKING",
  executing: "WORKING",
  approval: "WAITING",
  alert: "ATTENTION",
  error: "ATTENTION",
  offline: "OFFLINE",
}

export function parseRequestedPresence(value: unknown): PresenceMode {
  if (typeof value === "string" && (PRESENCE_MODES as readonly string[]).includes(value)) {
    return value as PresenceMode
  }
  return "neural"
}

export function presenceBudgets(density: number): { figure: number; field: number; galaxyStars: number } {
  const scale = Number.isFinite(density) && density > 0 ? density : 0
  return {
    figure: Math.round(FIGURE_BUDGET_SCALE * scale),
    field: Math.round(FIELD_BUDGET_SCALE * scale),
    galaxyStars: Math.round(GALAXY_STAR_BUDGET_SCALE * scale),
  }
}

/** Non-Galaxy formula is unchanged. Galaxy raises only the non-reduced cap. */
export function hudStarfieldCount(width: number, height: number, reduced: boolean, galaxy: boolean): number {
  if (reduced) return 90
  const area = Math.max(1, width) * Math.max(1, height)
  if (!galaxy) return Math.round(Math.min(420, Math.max(160, area / 9000)))
  return Math.round(Math.min(4000, Math.max(2400, area / 900)))
}

export function isGalaxyPresenceEffective(input: {
  requestedPresence: PresenceMode
  suiteOverride: boolean
  webglAvailable: boolean
}): boolean {
  if (input.suiteOverride) return false
  if (input.requestedPresence !== "galaxy") return false
  return input.webglAvailable
}

/**
 * Galaxy does not replace the figure `resolvePresenceShapeId` already chose.
 * Suite hex_aegis, a custom preset, and every persona shape — including Anzu's
 * stormbird — stay. Ref A/B apply only when that winner is `humanoid_bust`.
 */
export function galaxyFigureShapeId(input: {
  requestedPresence: PresenceMode
  resolvedShapeId: string
  suiteActive: boolean
  customPresetActive: boolean
  personaId?: string | null
}): string {
  return input.resolvedShapeId
}

export function galaxyPhaseLabel(phase: PresencePhase): string {
  return GALAXY_PHASE[phase]
}

function levelMarks(level: number): string {
  const filled = Math.max(0, Math.min(5, Math.round(level * 5)))
  return `${"•".repeat(filled)}${"·".repeat(5 - filled)}`
}

/** Full pill on the bust. Field-only reads may drop the rule and SYN-01. */
export function galaxyStatusText(
  phase: PresencePhase,
  options?: { analyser?: boolean; level?: number; bust?: boolean },
): string {
  const label = galaxyPhaseLabel(phase)
  if (options?.bust === false) return `STATUS: ${label}`
  const live = Boolean(options?.analyser) && (phase === "speaking" || phase === "listening")
  const level = options?.level ?? 0
  const marks = live && level > 0.04 ? levelMarks(level) : "·····"
  return `STATUS: ${label} | ${marks} | SYN-01`
}
