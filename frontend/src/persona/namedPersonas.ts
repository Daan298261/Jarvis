import { useEffect, useState } from "react"
import { api } from "../api"

export type PersonaAppearance = {
  voice_profile_id: string
  pitch: number
  speaking_rate: number
  volume: number
  orb_color: string
  accent_color: string
  glow: number
  animation: number
  scale: number
  specialists_auto_speak: boolean
}

export type NamedPersona = {
  id: string
  label: string
  role: string
  presence_shape_id: string
  voice_profile_id: string
  voice_profile_requested?: string | null
  default_colors: { orb: string; accent: string }
  appearance: PersonaAppearance
  is_default?: boolean
  is_pinned?: boolean
}

export type NamedPersonaState = {
  active: NamedPersona
  personas: NamedPersona[]
  default_id?: string
  pinned_ids?: string[]
  max_pinned?: number
}

const PHRASE: Record<string, string> = {
  anzu: "coordinating",
  mestor: "planning",
  nabu: "researching",
  enki: "coding",
  veles: "analysing threats",
  themis: "verifying security",
  aegir: "handling media",
  bragi: "writing",
  hermes: "messaging",
  heimdall: "watching",
  eir: "looking after the house",
  maia: "growing the audience",
  vulcan: "working the systems",
  umi: "reasoning deeply",

}

export const ROSTER_IDS = [
  "anzu", "mestor", "nabu", "enki", "veles", "themis", "aegir",
  "bragi", "hermes", "heimdall", "eir", "maia", "vulcan", "umi",
] as const

export type NamedPersonaId = typeof ROSTER_IDS[number]

/** Lightweight fallback data keeps every RFC-0137 avatar visible while the API loads. */
export const PERSONA_VISUALS: Record<NamedPersonaId, {
  shapeId: string
  orbColor: string
  accentColor: string
}> = {
  anzu: { shapeId: "stormbird", orbColor: "#9B1B30", accentColor: "#D4A017" },
  mestor: { shapeId: "command_facet", orbColor: "#1E3A8A", accentColor: "#F8FAFC" },
  nabu: { shapeId: "memory_rings", orbColor: "#D97706", accentColor: "#312E81" },
  enki: { shapeId: "code_cube", orbColor: "#22D3EE", accentColor: "#2563EB" },
  veles: { shapeId: "serpent_orbit", orbColor: "#5B21B6", accentColor: "#84CC16" },
  themis: { shapeId: "twin_shield", orbColor: "#E0F2FE", accentColor: "#FFFFFF" },
  aegir: { shapeId: "ocean_swell", orbColor: "#0D9488", accentColor: "#0C4A6E" },
  bragi: { shapeId: "waveform_letters", orbColor: "#C026D3", accentColor: "#EAB308" },
  hermes: { shapeId: "comet_trail", orbColor: "#FACC15", accentColor: "#06B6D4" },
  heimdall: { shapeId: "eye_radar", orbColor: "#F97316", accentColor: "#1D4ED8" },
  eir: { shapeId: "breath_leaf", orbColor: "#6EE7B7", accentColor: "#FDA4AF" },
  maia: { shapeId: "star_social", orbColor: "#FB7185", accentColor: "#F472B6" },
  vulcan: { shapeId: "forge_core", orbColor: "#EA580C", accentColor: "#DC2626" },
  umi: { shapeId: "opus_tide", orbColor: "#7C3AED", accentColor: "#A78BFA" },
}

export const PERSONA_LABELS: Record<string, string> = {
  anzu: "Anzu", mestor: "Mestor", nabu: "Nabu", enki: "Enki", veles: "Veles",
  themis: "Themis", aegir: "Aegir", bragi: "Bragi", hermes: "Hermes",
  heimdall: "Heimdall", eir: "Eir", maia: "Maia", vulcan: "Vulcan", umi: "Umi",
}

export function canonicalizePersonaId(raw: string): string {
  const key = (raw || "").trim().toLowerCase()
  if (key === "eagir" || key === "ægir") return "aegir"
  return key
}

export function personaCardSentence(mainId: string, specialistIds: string[]): string {
  const main = canonicalizePersonaId(mainId)
  if (!PERSONA_LABELS[main]) return ""
  const cleaned = specialistIds.map(canonicalizePersonaId)
  const others = ROSTER_IDS.filter((id) => cleaned.includes(id) && id !== main)
  if (!others.length) return ""
  const anzuAttached = main === "anzu" || cleaned.includes("anzu")
  const first = anzuAttached
    ? `${PERSONA_LABELS[main]} is coordinating.`
    : `${PERSONA_LABELS[main]} is ${PHRASE[main]}.`
  const rest = others.map((id) => `${PERSONA_LABELS[id]} is ${PHRASE[id]}.`)
  return [first, ...rest].join(" ")
}

let cache: NamedPersonaState | null = null
let selectionRevision = 0
const listeners = new Set<(state: NamedPersonaState | null) => void>()

function publish(state: NamedPersonaState | null) {
  cache = state
  listeners.forEach((listener) => listener(state))
}

function fallbackPersona(id: NamedPersonaId): NamedPersona {
  const visual = PERSONA_VISUALS[id]
  return {
    id,
    label: PERSONA_LABELS[id],
    role: "",
    presence_shape_id: visual.shapeId,
    voice_profile_id: "",
    default_colors: { orb: visual.orbColor, accent: visual.accentColor },
    appearance: {
      voice_profile_id: "",
      pitch: 0,
      speaking_rate: 1,
      volume: 1,
      orb_color: visual.orbColor,
      accent_color: visual.accentColor,
      glow: 0.82,
      animation: 0.72,
      scale: 1,
      specialists_auto_speak: false,
    },
  }
}

function fallbackState(activeId: NamedPersonaId): NamedPersonaState {
  const personas = ROSTER_IDS.map(fallbackPersona)
  return {
    active: personas.find((persona) => persona.id === activeId) ?? personas[0],
    personas,
    default_id: "anzu",
    pinned_ids: [],
    max_pinned: 5,
  }
}

export async function loadNamedPersonas(): Promise<NamedPersonaState> {
  const revision = selectionRevision
  const state = await api<NamedPersonaState>("/api/named-personas")
  // A mount-time catalog request can finish after the user has already picked
  // another persona. Never let that older response snap the avatar back.
  if (revision === selectionRevision) publish(state)
  return state
}

export async function selectNamedPersona(id: string): Promise<NamedPersonaState> {
  const previous = cache
  const canonicalId = canonicalizePersonaId(id)
  const knownId = ROSTER_IDS.find((personaId) => personaId === canonicalId)
  if (!knownId) throw new Error(`Unknown persona: ${id}`)
  const selected = previous?.personas.find((persona) => persona.id === canonicalId)
    ?? fallbackPersona(knownId)
  const optimistic = previous ?? fallbackState(knownId)
  const revision = ++selectionRevision
  // The figure must respond on the same click even while the local API is
  // starting. The server response can enrich voice/configuration afterwards.
  publish({ ...optimistic, active: selected })
  // A 409 is intentionally allowed to reach activateNamedPersona, which
  // installs the required neural pack and retries without losing this visual.
  const controller = new AbortController()
  const deadline = globalThis.setTimeout(() => controller.abort(), 8000)
  let state: NamedPersonaState
  try {
    state = await api<NamedPersonaState>("/api/named-personas", {
      method: "PUT",
      body: JSON.stringify({ id: canonicalId }),
      signal: controller.signal,
    })
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("Persona changed locally; Jarvis did not confirm the saved persona in time.")
    }
    throw error
  } finally {
    globalThis.clearTimeout(deadline)
  }
  if (revision === selectionRevision) publish(state)
  return state
}

export async function updateNamedPersonaPrefs(
  id: string,
  prefs: { setAsDefault?: boolean; pin?: boolean; apply?: boolean },
): Promise<NamedPersonaState> {
  const body: Record<string, unknown> = { id, apply: prefs.apply ?? false }
  if (prefs.setAsDefault) body.set_as_default = true
  if (prefs.pin !== undefined) body.pin = prefs.pin
  const state = await api<NamedPersonaState>("/api/named-personas", {
    method: "PUT",
    body: JSON.stringify(body),
  })
  publish(state)
  return state
}

export async function savePersonaAppearance(
  id: string,
  appearance: Partial<PersonaAppearance>,
): Promise<NamedPersonaState> {
  const state = await api<NamedPersonaState>("/api/named-personas", {
    method: "PUT",
    body: JSON.stringify({ id, appearance, apply: false }),
  })
  publish(state)
  return state
}

export async function resetNamedPersona(id: string): Promise<NamedPersonaState> {
  const state = await api<NamedPersonaState>("/api/named-personas", {
    method: "PUT",
    body: JSON.stringify({ id, reset: true }),
  })
  publish(state)
  return state
}

export function useNamedPersonas(): NamedPersonaState | null {
  const [state, setState] = useState<NamedPersonaState | null>(cache)
  useEffect(() => {
    let cancelled = false
    if (!cache) {
      loadNamedPersonas().catch(() => undefined)
    }
    const listener = (next: NamedPersonaState | null) => {
      if (!cancelled) setState(next)
    }
    listeners.add(listener)
    return () => {
      cancelled = true
      listeners.delete(listener)
    }
  }, [])
  return state
}
