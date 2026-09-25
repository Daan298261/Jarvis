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
}

export type NamedPersonaState = {
  active: NamedPersona
  personas: NamedPersona[]
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

}

export const ROSTER_IDS = [
  "anzu", "mestor", "nabu", "enki", "veles", "themis", "aegir",
  "bragi", "hermes", "heimdall", "eir", "maia", "vulcan",
] as const

export const PERSONA_LABELS: Record<string, string> = {
  anzu: "Anzu", mestor: "Mestor", nabu: "Nabu", enki: "Enki", veles: "Veles",
  themis: "Themis", aegir: "Aegir", bragi: "Bragi", hermes: "Hermes",
  heimdall: "Heimdall", eir: "Eir", maia: "Maia", vulcan: "Vulcan",
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
const listeners = new Set<(state: NamedPersonaState | null) => void>()

function publish(state: NamedPersonaState | null) {
  cache = state
  listeners.forEach((listener) => listener(state))
}

export async function loadNamedPersonas(): Promise<NamedPersonaState> {
  const state = await api<NamedPersonaState>("/api/named-personas")
  publish(state)
  return state
}

export async function selectNamedPersona(id: string): Promise<NamedPersonaState> {
  const state = await api<NamedPersonaState>("/api/named-personas", {
    method: "PUT",
    body: JSON.stringify({ id }),
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
    body: JSON.stringify({ id, appearance }),
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
