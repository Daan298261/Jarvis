import { useEffect, useId, useRef, useState } from "react"
import { createPortal } from "react-dom"
import {
  applyPreviewFromJob,
  clearActiveCustomPresence,
  createCustomPresenceJob,
  defaultNameFromPrompt,
  deleteCustomPresencePreset,
  discardCustomPresencePreview,
  formatCustomPresenceError,
  saveCustomPresencePreset,
  setDefaultCustomPresence,
  setShapeBeforeWizard,
  useCustomPresence,
  type CustomPresenceJob,
} from "./customPresence"
import { resolvePresenceShapeId } from "./resolvePresenceShapeId"
import { useHexStrikeSuiteActive } from "../hud/hexstrikeSuite"
import { useNamedPersonas } from "../persona/namedPersonas"
import type { PresentationSettings } from "./presenceTypes"
import "./custom-presence.css"

type CustomPresencePanelProps = {
  settings: PresentationSettings
}

type WizardStep = "input" | "generating" | "preview"

function canPreviewOnCloud(settings: PresentationSettings): boolean {
  if (settings.shell === "classic" || settings.requestedPresence === "none") return false
  return settings.requestedPresence === "humanoid" || settings.requestedPresence === "particle_bust"
}

export function CustomPresencePanel({ settings }: CustomPresencePanelProps) {
  const { state, preview } = useCustomPresence()
  const { active: hexStrikeActive } = useHexStrikeSuiteActive()
  const namedPersonas = useNamedPersonas()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [listError, setListError] = useState("")
  const titleId = useId()

  const personaShape = namedPersonas?.active?.presence_shape_id || "stormbird"
  const activeCustom = preview?.shapeId || state?.active_shape_id || ""
  const currentResolved = resolvePresenceShapeId(hexStrikeActive, activeCustom, personaShape)

  async function onDelete(presetId: string) {
    setBusy(true)
    setListError("")
    try {
      await deleteCustomPresencePreset(presetId)
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Could not delete that look.")
    } finally {
      setBusy(false)
    }
  }

  async function onSetDefault(presetId: string) {
    setBusy(true)
    setListError("")
    try {
      await setDefaultCustomPresence(presetId)
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Could not set the default look.")
    } finally {
      setBusy(false)
    }
  }

  async function onClearActive() {
    setBusy(true)
    setListError("")
    try {
      await clearActiveCustomPresence()
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Could not clear the active look.")
    } finally {
      setBusy(false)
    }
  }

  function openWizard() {
    setShapeBeforeWizard(currentResolved)
    setOpen(true)
  }

  return (
    <div className="custom-presence-panel">
      <div className="custom-presence-panel-header">
        <p className="custom-presence-panel-lede">
          Anzu 1.0 custom looks are built only from the flowing orbs — not meshes, textures, or HTML.
        </p>
        <button type="button" className="btn" disabled={busy} onClick={openWizard}>
          Add new UI
        </button>
      </div>

      {state && state.presets.length > 0 && (
        <ul className="custom-presence-preset-list" aria-label="Saved custom looks">
          {state.presets.map((preset) => {
            const isDefault = Boolean(preset.default) || preset.id === state.default_preset_id
            const isActive = preset.id === state.active_preset_id
            return (
              <li key={preset.id} className="custom-presence-preset-row">
                <span className="custom-presence-preset-name">
                  {preset.name}
                  {isActive ? " · active" : ""}
                </span>
                {isDefault && <span className="custom-presence-default-badge">Default</span>}
                <div className="custom-presence-preset-actions">
                  {!isDefault && (
                    <button
                      type="button"
                      className="btn secondary"
                      disabled={busy}
                      onClick={() => void onSetDefault(preset.id)}
                    >
                      Set as default
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn secondary"
                    disabled={busy}
                    onClick={() => void onDelete(preset.id)}
                  >
                    Delete
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {state?.active_preset_id && (
        <button type="button" className="btn secondary" disabled={busy} onClick={() => void onClearActive()}>
          Clear active custom look
        </button>
      )}

      {listError && (
        <p className="custom-presence-wizard-status" data-tone="error" role="alert">
          {listError}
        </p>
      )}

      {open &&
        createPortal(
          <CustomPresenceWizard
            titleId={titleId}
            settings={settings}
            onClose={() => setOpen(false)}
          />,
          document.body,
        )}
    </div>
  )
}

function CustomPresenceWizard({
  titleId,
  settings,
  onClose,
}: {
  titleId: string
  settings: PresentationSettings
  onClose: () => void
}) {
  const [step, setStep] = useState<WizardStep>("input")
  const [promptText, setPromptText] = useState("")
  const [image, setImage] = useState<File | null>(null)
  const [saveName, setSaveName] = useState("")
  const [job, setJob] = useState<CustomPresenceJob | null>(null)
  const [error, setError] = useState("")
  const [statusNote, setStatusNote] = useState("")
  const [busy, setBusy] = useState(false)
  const firstFieldRef = useRef<HTMLTextAreaElement>(null)
  const previewReady = canPreviewOnCloud(settings)

  useEffect(() => {
    firstFieldRef.current?.focus()
  }, [])

  const busyRef = useRef(busy)
  const jobRef = useRef(job)
  busyRef.current = busy
  jobRef.current = job

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape" || busyRef.current) return
      event.preventDefault()
      const activeJob = jobRef.current
      void (async () => {
        if (busyRef.current) return
        setBusy(true)
        try {
          if (activeJob?.id) await discardCustomPresencePreview(activeJob.id)
          setShapeBeforeWizard(null)
          onClose()
        } finally {
          setBusy(false)
        }
      })()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  async function handleGenerate() {
    setError("")
    setStatusNote("")
    if (!promptText.trim() && !image) {
      setError("Enter a text description, choose an image, or both.")
      return
    }
    setBusy(true)
    setStep("generating")
    setStatusNote("Generating with Anzu…")
    try {
      const next = await createCustomPresenceJob({ promptText, image })
      setJob(next)
      if (next.status === "succeeded" && next.orb_composition && next.preview_shape_id) {
        applyPreviewFromJob(next)
        setSaveName(defaultNameFromPrompt(next.prompt_text || promptText))
        setStep("preview")
        if (!previewReady) {
          setStatusNote(
            "Preview needs Humanoid HUD or Particle bust. Switch presence with the Appearance controls — Anzu will not change the shell for you.",
          )
        } else {
          setStatusNote("Preview is morphing on the existing orb cloud.")
        }
      } else if (next.status === "failed" || next.status === "rejected") {
        setStep("input")
        setStatusNote("")
        setError(formatCustomPresenceError(null, next))
      } else {
        setStep("input")
        setError(`Unexpected job status: ${next.status}`)
      }
    } catch (err) {
      setStep("input")
      setStatusNote("")
      setError(formatCustomPresenceError(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleSave(setDefault: boolean) {
    if (!job?.id) return
    const name = (saveName || defaultNameFromPrompt(job.prompt_text || promptText)).trim()
    if (!name) {
      setError("Name this look before saving.")
      return
    }
    setBusy(true)
    setError("")
    try {
      await saveCustomPresencePreset({
        jobId: job.id,
        name,
        setDefault,
      })
      setShapeBeforeWizard(null)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this look.")
    } finally {
      setBusy(false)
    }
  }

  async function handleDiscardAndClose() {
    if (busy) return
    setBusy(true)
    try {
      if (job?.id) {
        await discardCustomPresencePreview(job.id)
      }
      setShapeBeforeWizard(null)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="custom-presence-wizard-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) void handleDiscardAndClose()
      }}
    >
      <div
        className="custom-presence-wizard"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h2 id={titleId}>Add new UI</h2>
        <p className="custom-presence-wizard-sub">
          Describe a presence look for Anzu 1.0. The result is composed only from flowing orbs on the
          existing cloud — no second canvas, meshes, or HTML chrome.
        </p>

        {step !== "preview" && (
          <>
            <label>
              Look description
              <textarea
                ref={firstFieldRef}
                value={promptText}
                disabled={busy}
                aria-label="Look description"
                placeholder="e.g. a deep crimson core with twin gold wing arcs"
                onChange={(event) => setPromptText(event.target.value)}
              />
            </label>
            <label>
              Reference image (optional)
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp,image/*"
                disabled={busy}
                aria-label="Reference image"
                onChange={(event) => {
                  const file = event.target.files?.[0] || null
                  setImage(file)
                }}
              />
            </label>
          </>
        )}

        {step === "preview" && (
          <label>
            Name
            <input
              type="text"
              maxLength={80}
              value={saveName}
              disabled={busy}
              aria-label="Custom look name"
              onChange={(event) => setSaveName(event.target.value)}
            />
          </label>
        )}

        {statusNote && (
          <p
            className="custom-presence-wizard-status"
            data-tone={!previewReady && step === "preview" ? "warn" : "ok"}
            role="status"
          >
            {statusNote}
          </p>
        )}
        {error && (
          <p className="custom-presence-wizard-status" data-tone="error" role="alert">
            {error}
          </p>
        )}

        <div className="custom-presence-wizard-actions">
          {step !== "preview" && (
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => void handleGenerate()}
            >
              {busy ? "Generating…" : "Generate"}
            </button>
          )}
          {step === "preview" && (
            <>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => void handleSave(true)}
              >
                Set as default
              </button>
              <button
                type="button"
                className="btn secondary"
                disabled={busy}
                onClick={() => void handleSave(false)}
              >
                Save as named custom UI
              </button>
            </>
          )}
          <button
            type="button"
            className="btn secondary"
            disabled={busy}
            onClick={() => void handleDiscardAndClose()}
          >
            Discard
          </button>
        </div>
      </div>
    </div>
  )
}
