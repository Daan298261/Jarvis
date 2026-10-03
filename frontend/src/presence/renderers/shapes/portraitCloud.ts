import { registerPresenceShape } from "./catalog"
import { buildHumanoidBustField } from "./humanoidBust"
import type { ParticleOrb } from "../particleTypes"

const pending = new Map<string, Promise<string>>()
let terrain: Promise<ParticleOrb[]> | undefined

/** Windows embedded browsers can leave image.decode() pending indefinitely. */
function loadPortraitImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    let settled = false
    const ready = () => {
      if (settled) return
      settled = true
      resolve(image)
    }
    image.onload = ready
    image.onerror = () => {
      if (settled) return
      settled = true
      reject(new Error(`Avatar artwork is unavailable: ${url}`))
    }
    image.src = url
    image.decode?.().then(ready).catch(() => {
      // Some WebView builds reject decode() even though onload succeeds.
    })
  })
}

function prepareTerrain(): Promise<ParticleOrb[]> {
  return terrain ??= (async () => {
    const image = await loadPortraitImage("/presence/jarvis-original/backdrop.webp")
    const canvas = document.createElement("canvas")
    canvas.width = 768
    canvas.height = 432
    const ctx = canvas.getContext("2d", { willReadFrequently: true })
    if (!ctx) throw new Error("Cannot prepare particle terrain")
    ctx.drawImage(image, 0, 0, 768, 432)
    const pixels = ctx.getImageData(0, 0, 768, 432).data
    const points: ParticleOrb[] = []
    for (let y = 0; y < 432; y++) for (let x = 0; x < 768; x++) {
      const i = (y * 768 + x) * 4
      const r = pixels[i] / 255, g = pixels[i + 1] / 255, b = pixels[i + 2] / 255
      if (Math.max(r, g, b) < 0.24) continue
      points.push({ x: (x / 767 - 0.5) * 9, y: (0.5 - y / 431) * 4.1 - 0.25,
        z: -1.4, size: 2.6, light: 1.5, gold: 0, flow: 1,
        color: [linear(r), linear(g), linear(b), 1] })
    }
    return points
  })().catch(error => { terrain = undefined; throw error })
}

const linear = (v: number) => v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)

/** Decode once; every visible pixel becomes a luminous sample in the shared cloud. */
export function preparePortraitCloud(url: string, persona: string): Promise<string> {
  const key = `${persona}:${url}`
  const cached = pending.get(key)
  if (cached) return cached
  const promise = (async () => {
    const image = await loadPortraitImage(url)
    const canvas = document.createElement("canvas")
    const resolution = persona === "humanoid" ? 512 : 256
    canvas.width = resolution
    canvas.height = Math.round(resolution * image.height / image.width)
    const height = canvas.height
    const context = canvas.getContext("2d", { willReadFrequently: true })
    if (!context) throw new Error("Cannot prepare avatar particles")
    context.drawImage(image, 0, 0, resolution, height)
    const pixels = context.getImageData(0, 0, resolution, height).data
    const points: ParticleOrb[] = []
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < resolution; x++) {
        const i = (y * resolution + x) * 4
        const alpha = pixels[i + 3] / 255
        if (alpha < 0.12) continue
        const r = pixels[i] / 255, g = pixels[i + 1] / 255, b = pixels[i + 2] / 255
        const luminance = r * 0.2126 + g * 0.7152 + b * 0.0722
        if (Math.max(r, g, b) < 0.08) continue
        points.push({
          x: (x / (resolution - 1) - 0.5) * 3.1,
          y: (0.5 - y / (height - 1)) * 3.1 * height / resolution,
          z: luminance * 0.22,
          size: persona === "humanoid" ? 2.2 : 1.7,
          light: alpha * (0.65 + luminance * 0.6),
          gold: 0,
          flow: 0,
          color: [linear(r), linear(g), linear(b), 1],
        })
      }
    }
    if (!points.length) throw new Error("Avatar artwork contains no visible particles")
    const field = persona === "humanoid" ? await prepareTerrain().catch(() => undefined) : undefined
    const id = `portrait_${persona}`
    registerPresenceShape({
      id, label: `${persona} particle avatar`,
      buildFigure: () => points,
      buildField: field ? () => field : buildHumanoidBustField,
      framing: { yaw: 0, position: [0, 0, 0], fitMargin: 0.83 },
      appearance: { pointScale: 1, depthSoftness: 1 },
    })
    return id
  })()
  pending.set(key, promise)
  promise.catch(() => pending.delete(key))
  return promise
}
