import type { ParticleOrb, PresenceShapeDefinition, PresenceShapeFraming } from "../particleTypes"
import { resolvePresenceShape } from "./catalog"
import { fillSphere, makeRng, pushOrb, ring } from "./figureKit"

export type OrbCompositionMotion = "pulse" | "orbit" | "breathe" | "static"

export type OrbCompositionLayer = {
  kind: "sphere" | "ring" | "arc" | "orbit" | "sparks" | "shape_sample"
  count_scale?: number
  radius?: number
  y?: number
  gold?: number
  light?: number
  flow?: number
  size?: number
  motion?: OrbCompositionMotion
  tilt?: number
  shape_id?: string
}

export type OrbComposition = {
  version: 1
  orb_color: string
  accent_color: string
  framing?: {
    yaw?: number
    position?: [number, number, number] | number[]
  }
  layers: OrbCompositionLayer[]
}

const FORBIDDEN = ["mesh", "gltf", "glb", "texture", "material", "html", "css", "silhouette"] as const
const ALLOWED_KINDS = new Set(["sphere", "ring", "arc", "orbit", "sparks", "shape_sample"])
const COLOR_RE = /^#[0-9A-Fa-f]{6}$/

function containsForbidden(value: string): boolean {
  const lower = value.toLowerCase()
  return FORBIDDEN.some((token) => lower.includes(token))
}

function scanForbidden(obj: unknown, errors: string[]): void {
  if (obj && typeof obj === "object") {
    if (Array.isArray(obj)) {
      for (const item of obj) scanForbidden(item, errors)
      return
    }
    for (const [key, val] of Object.entries(obj as Record<string, unknown>)) {
      if (containsForbidden(key)) errors.push(`forbidden token in key: ${key}`)
      scanForbidden(val, errors)
    }
    return
  }
  if (typeof obj === "string" && containsForbidden(obj)) {
    errors.push(`forbidden token in string: ${obj.slice(0, 80)}`)
  }
}

/** Client-side validation mirror of Phase A. Empty array means valid. */
export function validateOrbComposition(raw: unknown): string[] {
  const errors: string[] = []
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return ["orb_composition must be a JSON object"]
  }
  const comp = raw as Record<string, unknown>
  scanForbidden(comp, errors)
  if (comp.version !== 1) errors.push("version must be 1")
  if (typeof comp.orb_color !== "string" || !COLOR_RE.test(comp.orb_color)) {
    errors.push("orb_color must be #RRGGBB")
  }
  if (typeof comp.accent_color !== "string" || !COLOR_RE.test(comp.accent_color)) {
    errors.push("accent_color must be #RRGGBB")
  }
  const layers = comp.layers
  if (!Array.isArray(layers)) {
    errors.push("layers must be an array")
    return errors
  }
  if (layers.length < 1 || layers.length > 24) {
    errors.push("layers must contain 1..24 items")
  }
  for (let i = 0; i < layers.length; i++) {
    const layer = layers[i]
    if (!layer || typeof layer !== "object" || Array.isArray(layer)) {
      errors.push(`layers[${i}] must be an object`)
      continue
    }
    const kind = (layer as OrbCompositionLayer).kind
    if (!ALLOWED_KINDS.has(kind)) {
      errors.push(`layers[${i}].kind invalid: ${JSON.stringify(kind)}`)
      continue
    }
    if (kind === "shape_sample") {
      const sid = (layer as OrbCompositionLayer).shape_id
      if (!sid || typeof sid !== "string") {
        errors.push(`layers[${i}].shape_id required for shape_sample`)
      } else if (sid.startsWith("custom_ui_")) {
        errors.push(`layers[${i}].shape_id must not be custom_ui_*`)
      }
    }
  }
  return errors
}

function motionFlow(motion: OrbCompositionMotion | undefined, flow: number | undefined): number {
  if (typeof flow === "number") return flow
  if (motion === "pulse") return 2
  if (motion === "orbit") return 1
  if (motion === "breathe") return 0.4
  return 0
}

function layerCount(base: number, density: number, scale: number): number {
  return Math.max(1, Math.round(base * density * Math.max(0.05, Math.min(4, scale))))
}

function appendArc(
  orbs: ParticleOrb[],
  random: () => number,
  count: number,
  radius: number,
  y: number,
  gold: number,
  light: number,
  flow: number,
  size: number,
  density: number,
): void {
  const half = Math.max(1, Math.floor(count / 2))
  for (const side of [-1, 1] as const) {
    for (let i = 0; i < half; i++) {
      const t = i / half
      const ang = -0.4 + t * 2.5
      const reach = radius * (0.45 + Math.sin(t * Math.PI) * 0.95)
      pushOrb(
        orbs,
        side * Math.cos(ang) * reach,
        y + Math.sin(ang) * radius * 0.55,
        Math.sin(t * 6) * 0.08 + (random() - 0.5) * 0.02,
        t > 0.55 ? Math.max(gold, 0.85) : gold,
        light,
        flow,
        size,
        density,
      )
    }
  }
}

function appendOrbit(
  orbs: ParticleOrb[],
  random: () => number,
  count: number,
  radius: number,
  y: number,
  gold: number,
  light: number,
  flow: number,
  size: number,
  density: number,
  tilt: number,
): void {
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2
    const rx = radius * (0.85 + random() * 0.2)
    const rz = radius * (0.55 + random() * 0.25)
    const x = Math.cos(a) * rx
    const z = Math.sin(a) * rz
    const y2 = y + Math.sin(a) * tilt * radius
    pushOrb(orbs, x, y2, z, gold, light, flow, size, density)
  }
}

function appendSparks(
  orbs: ParticleOrb[],
  random: () => number,
  count: number,
  radius: number,
  y: number,
  gold: number,
  light: number,
  flow: number,
  size: number,
  density: number,
): void {
  for (let i = 0; i < count; i++) {
    const side = i % 2 === 0 ? -1 : 1
    pushOrb(
      orbs,
      side * (radius * 0.25 + random() * radius * 1.1),
      y + random() * radius,
      (random() - 0.5) * radius * 0.35,
      gold,
      light,
      flow,
      size,
      density,
    )
  }
}

/** Pure buildFigure from a validated orb_composition v1. */
export function buildFigureFromComposition(composition: OrbComposition, density: number): ParticleOrb[] {
  const errors = validateOrbComposition(composition)
  if (errors.length) {
    throw new Error(errors.join("; "))
  }
  const random = makeRng(0x0138a1)
  const orbs: ParticleOrb[] = []
  for (const layer of composition.layers) {
    const scale = typeof layer.count_scale === "number" ? layer.count_scale : 1
    const radius = typeof layer.radius === "number" ? layer.radius : 0.7
    const y = typeof layer.y === "number" ? layer.y : 0.08
    const gold = typeof layer.gold === "number" ? layer.gold : 0.2
    const light = typeof layer.light === "number" ? layer.light : 1.2
    const size = typeof layer.size === "number" ? layer.size : 1.35
    const flow = motionFlow(layer.motion, layer.flow)
    const tilt = typeof layer.tilt === "number" ? layer.tilt : 0.05

    if (layer.kind === "sphere") {
      fillSphere(
        orbs,
        random,
        layerCount(2200, density, scale),
        radius,
        y,
        gold,
        light,
        flow,
        size,
        density,
      )
    } else if (layer.kind === "ring") {
      ring(
        orbs,
        random,
        layerCount(200, density, scale),
        radius,
        y,
        gold,
        light,
        flow,
        size,
        density,
        tilt,
      )
    } else if (layer.kind === "arc") {
      appendArc(orbs, random, layerCount(420, density, scale), radius, y, gold, light, flow, size, density)
    } else if (layer.kind === "orbit") {
      appendOrbit(orbs, random, layerCount(280, density, scale), radius, y, gold, light, flow, size, density, tilt)
    } else if (layer.kind === "sparks") {
      appendSparks(orbs, random, layerCount(180, density, scale), radius, y, gold, light, flow, size, density)
    } else if (layer.kind === "shape_sample") {
      const sid = (layer.shape_id || "").trim()
      if (!sid || sid.startsWith("custom_ui_")) continue
      const sampleDensity = density * Math.max(0.05, Math.min(4, scale))
      const sampled = resolvePresenceShape(sid).buildFigure(sampleDensity)
      for (const orb of sampled) orbs.push({ ...orb })
    }
  }
  return orbs
}

export function framingFromComposition(composition: OrbComposition): PresenceShapeFraming | undefined {
  const framing = composition.framing
  if (!framing) return undefined
  const position = framing.position
  const out: PresenceShapeFraming = {}
  if (typeof framing.yaw === "number") out.yaw = framing.yaw
  if (Array.isArray(position) && position.length === 3 && position.every((v) => typeof v === "number")) {
    out.position = [position[0], position[1], position[2]]
  }
  return out
}

export function definitionFromComposition(
  shapeId: string,
  label: string,
  composition: OrbComposition,
): PresenceShapeDefinition {
  const framing = framingFromComposition(composition)
  return {
    id: shapeId,
    label,
    buildFigure: (density) => buildFigureFromComposition(composition, density),
    framing,
  }
}
