import { useEffect, useState } from "react"
import { api, apiForm, isApiError } from "../api"
import {
  definitionFromComposition,
  type OrbComposition,
  validateOrbComposition,
} from "./renderers/shapes/orbComposition"
import {
  registerCustomPresenceShape,
  unregisterPresenceShape,
} from "./renderers/shapes/catalog"

export type CustomPresenceSource = "text_prompt" | "image" | "text_and_image"

export type CustomPresencePreset = {
  id: string
  name: string
  source: CustomPresenceSource
  source_image_ref: string
  prompt_text: string
  orb_composition: OrbComposition
  shape_id: string
  default: boolean
  created_at: string
  updated_at: string
}

export type CustomPresenceState = {
  presets: CustomPresencePreset[]
  active_preset_id: string
  default_preset_id: string
  active_shape_id: string
  registered_shapes?: string[]
}

export type CustomPresenceJobError = {
  code: string
  message: string
}

export type CustomPresenceJob = {
  id: string
  status: "queued" | "running" | "succeeded" | "failed" | "rejected"
  prompt_text: string
  source: CustomPresenceSource | string
  source_image_ref: string
  orb_composition: OrbComposition | null
  preview_shape_id: string
  error: CustomPresenceJobError | null
  created_at: string
  updated_at: string
}

/** Live preview override while the Add new UI wizard has a succeeded job. */
export type CustomPresencePreview = {
  jobId: string
  shapeId: string
  composition: OrbComposition
  promptText: string
}

type Store = {
  state: CustomPresenceState | null
  preview: CustomPresencePreview | null
  /** Resolved shape id before the wizard opened (for discard morph-back). */
  shapeBeforeWizard: string | null
}

const store: Store = {
  state: null,
  preview: null,
  shapeBeforeWizard: null,
}

const listeners = new Set<() => void>()

function publish() {
  listeners.forEach((listener) => listener())
}

function registerPresetsFromState(state: CustomPresenceState) {
  for (const preset of state.presets) {
    const errors = validateOrbComposition(preset.orb_composition)
    if (errors.length) continue
    try {
      registerCustomPresenceShape(
        definitionFromComposition(
          preset.shape_id || `custom_ui_${preset.id}`,
          preset.name || "Custom look",
          preset.orb_composition,
        ),
      )
    } catch {
      // Protected / invalid ids stay fail-closed; skip.
    }
  }
}

function setState(state: CustomPresenceState) {
  registerPresetsFromState(state)
  store.state = state
  publish()
}

export function getCustomPresenceState(): CustomPresenceState | null {
  return store.state
}

export function getCustomPresencePreview(): CustomPresencePreview | null {
  return store.preview
}

export function getShapeBeforeWizard(): string | null {
  return store.shapeBeforeWizard
}

export function setShapeBeforeWizard(shapeId: string | null) {
  store.shapeBeforeWizard = shapeId
}

/** Effective custom shape for precedence: preview wins over saved active. */
export function getActiveCustomShapeId(): string {
  if (store.preview?.shapeId) return store.preview.shapeId
  return (store.state?.active_shape_id || "").trim()
}

export function getActiveCustomComposition(): OrbComposition | null {
  if (store.preview?.composition) return store.preview.composition
  const state = store.state
  if (!state?.active_preset_id) return null
  const preset = state.presets.find((row) => row.id === state.active_preset_id)
  return preset?.orb_composition ?? null
}

export function formatCustomPresenceError(err: unknown, job?: CustomPresenceJob | null): string {
  if (job?.error) {
    const code = job.error.code || ""
    const message = job.error.message || code
    if (code === "model_unavailable") {
      return message && message !== code
        ? message
        : "Anzu is not loaded. Custom UI generation needs the local model."
    }
    if (code === "vision_unavailable") {
      return message && message !== code
        ? message
        : "Vision is not loaded. Image looks need mmproj attached; text-only still works."
    }
    if (code === "constraint_rejected") {
      return message && message !== code
        ? message
        : "Anzu returned a look that is not built from flowing orbs. Nothing was saved."
    }
    return message || code || "Generation failed."
  }
  if (isApiError(err)) {
    const body = err.body as
      | {
          detail?: unknown
          error?: { code?: string; message?: string }
        }
      | null
    const nested =
      body && typeof body === "object"
        ? body.error
          || (body.detail && typeof body.detail === "object" && !Array.isArray(body.detail)
            ? (body.detail as { error?: { code?: string; message?: string } }).error
            : undefined)
        : undefined
    if (nested?.code) {
      return formatCustomPresenceError(null, {
        id: "",
        status: "failed",
        prompt_text: "",
        source: "text_prompt",
        source_image_ref: "",
        orb_composition: null,
        preview_shape_id: "",
        error: {
          code: nested.code,
          message: nested.message || nested.code,
        },
        created_at: "",
        updated_at: "",
      })
    }
    if (err.status === 413) return "That image is too large for custom UI upload."
    return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return "Could not generate a custom look."
}

export async function loadCustomPresence(): Promise<CustomPresenceState> {
  const state = await api<CustomPresenceState>("/api/custom-presence")
  setState(state)
  return state
}

export async function createCustomPresenceJob(opts: {
  promptText: string
  image?: File | null
}): Promise<CustomPresenceJob> {
  const text = (opts.promptText || "").trim()
  const image = opts.image || null
  if (!text && !image) {
    throw new Error("Enter a text description, choose an image, or both.")
  }
  let job: CustomPresenceJob
  if (image) {
    const form = new FormData()
    if (text) form.set("prompt_text", text)
    form.set("image", image, image.name || "upload.png")
    job = await apiForm<CustomPresenceJob>("/api/custom-presence/jobs", form)
  } else {
    job = await api<CustomPresenceJob>("/api/custom-presence/jobs", {
      method: "POST",
      body: JSON.stringify({ prompt_text: text }),
    })
  }
  return job
}

export async function getCustomPresenceJob(jobId: string): Promise<CustomPresenceJob> {
  return api<CustomPresenceJob>(`/api/custom-presence/jobs/${encodeURIComponent(jobId)}`)
}

export function applyPreviewFromJob(job: CustomPresenceJob): void {
  if (job.status !== "succeeded" || !job.orb_composition || !job.preview_shape_id) {
    throw new Error("Job did not return a preview look.")
  }
  const errors = validateOrbComposition(job.orb_composition)
  if (errors.length) {
    throw new Error(errors.join("; "))
  }
  registerCustomPresenceShape(
    definitionFromComposition(job.preview_shape_id, "Custom preview", job.orb_composition),
  )
  store.preview = {
    jobId: job.id,
    shapeId: job.preview_shape_id,
    composition: job.orb_composition,
    promptText: job.prompt_text || "",
  }
  publish()
}

export async function discardCustomPresencePreview(jobId: string): Promise<void> {
  const preview = store.preview
  if (preview && preview.jobId === jobId) {
    unregisterPresenceShape(preview.shapeId)
    store.preview = null
    publish()
  }
  try {
    await api(`/api/custom-presence/jobs/${encodeURIComponent(jobId)}/discard`, { method: "POST" })
  } catch {
    // Local unregister already cleared the cloud; server discard is best-effort.
  }
}

export async function saveCustomPresencePreset(opts: {
  jobId: string
  name: string
  setDefault: boolean
}): Promise<CustomPresenceState> {
  const state = await api<CustomPresenceState>("/api/custom-presence/presets", {
    method: "POST",
    body: JSON.stringify({
      job_id: opts.jobId,
      name: opts.name,
      set_default: opts.setDefault,
    }),
  })
  const preview = store.preview
  if (preview && preview.jobId === opts.jobId) {
    unregisterPresenceShape(preview.shapeId)
    store.preview = null
  }
  setState(state)
  return state
}

export async function setDefaultCustomPresence(presetId: string): Promise<CustomPresenceState> {
  const state = await api<CustomPresenceState>("/api/custom-presence/default", {
    method: "PUT",
    body: JSON.stringify({ preset_id: presetId }),
  })
  setState(state)
  return state
}

export async function deleteCustomPresencePreset(presetId: string): Promise<CustomPresenceState> {
  const state = await api<CustomPresenceState>(
    `/api/custom-presence/presets/${encodeURIComponent(presetId)}`,
    { method: "DELETE" },
  )
  setState(state)
  return state
}

export async function clearActiveCustomPresence(): Promise<CustomPresenceState> {
  const state = await api<CustomPresenceState>("/api/custom-presence/active/clear", {
    method: "POST",
  })
  setState(state)
  return state
}

export function useCustomPresence(): {
  state: CustomPresenceState | null
  preview: CustomPresencePreview | null
  activeShapeId: string
} {
  const [, setTick] = useState(0)
  useEffect(() => {
    let cancelled = false
    if (!store.state) {
      loadCustomPresence().catch(() => undefined)
    }
    const listener = () => {
      if (!cancelled) setTick((n) => n + 1)
    }
    listeners.add(listener)
    return () => {
      cancelled = true
      listeners.delete(listener)
    }
  }, [])
  return {
    state: store.state,
    preview: store.preview,
    activeShapeId: getActiveCustomShapeId(),
  }
}

export function defaultNameFromPrompt(promptText: string): string {
  const trimmed = (promptText || "").trim().slice(0, 48)
  return trimmed || "Custom look"
}
