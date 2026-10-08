import { useEffect, useRef, useState } from "react"
import { loadVoiceProfileCatalog, type VoiceProfileCatalog } from "../tts/voiceProfiles"
import { activateNamedPersona } from "./activateNamedPersona"
import {
  PERSONA_LABELS,
  PERSONA_VISUALS,
  resetNamedPersona,
  ROSTER_IDS,
  savePersonaAppearance,
  updateNamedPersonaPrefs,
  useNamedPersonas,
  type PersonaAppearance,
} from "./namedPersonas"
import { SpecialistShapeMark } from "./SpecialistShapeMark"
import { updatePresentation, usePresentationSettings } from "../presence/presentationSettings"
import {
  MYTHIC_LIVE_B_AVATAR_ID,
  MYTHIC_PORTRAIT_A_AVATAR_ID,
  usesMythicLiveVariantB,
} from "../presence/mythicPersonaVariant"
import "./named-persona.css"

const SYSTEM_VOICE = "windows_natural_en_v1"

export function NamedPersonaControls() {
  const state = useNamedPersonas()
  const presentation = usePresentationSettings()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [progress, setProgress] = useState("")
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceProfileCatalog | null>(null)
  const chooseRevision = useRef(0)
  const active = state?.active
  const appearance = active?.appearance
  const options = state?.personas?.length
    ? state.personas
    : ROSTER_IDS.map((id) => ({
        id,
        label: PERSONA_LABELS[id] || id,
        role: "",
        presence_shape_id: PERSONA_VISUALS[id].shapeId,
        default_colors: {
          orb: PERSONA_VISUALS[id].orbColor,
          accent: PERSONA_VISUALS[id].accentColor,
        },
      }))

  useEffect(() => {
    let cancelled = false
    void loadVoiceProfileCatalog().then((catalog) => {
      if (!cancelled) setVoiceCatalog(catalog)
    })
    return () => { cancelled = true }
  }, [])

  async function choose(id: string) {
    const revision = ++chooseRevision.current
    setBusy(true)
    setPendingId(id)
    setError("")
    setProgress("")
    try {
      await activateNamedPersona(id, { onProgress: setProgress })
      void loadVoiceProfileCatalog().then(setVoiceCatalog).catch(() => undefined)
    } catch (err) {
      if (revision === chooseRevision.current) {
        setError(err instanceof Error ? err.message : "Could not update the named persona.")
      }
    } finally {
      if (revision === chooseRevision.current) {
        setPendingId(null)
        setProgress("")
        setBusy(false)
      }
    }
  }

  const activeVoice = voiceCatalog?.profiles.find((profile) => profile.id === active?.voice_profile_id)

  async function run(task: () => Promise<unknown>) {
    setBusy(true)
    setError("")
    try {
      await task()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the named persona.")
    } finally {
      setBusy(false)
    }
  }

  async function patch(partial: Partial<PersonaAppearance>) {
    if (!active?.id) return
    if (partial.voice_profile_id === SYSTEM_VOICE) {
      setError("Named personas keep a neural voice. Windows SAPI is not a persona voice.")
      return
    }
    setError("")
    try {
      await savePersonaAppearance(active.id, partial)
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return
      setError(err instanceof Error ? err.message : "Could not save the persona appearance.")
    }
  }

  return (
    <div className="named-persona-controls">
      <label>
        Named persona
        <select
          aria-label="Named persona"
          value={pendingId || active?.id || "anzu"}
          onChange={(event) => {
            const id = event.target.value
            void choose(id)
          }}
        >
          {options.map((persona) => (
            <option key={persona.id} value={persona.id}>
              {persona.label}
            </option>
          ))}
        </select>
      </label>
      <div className="named-persona-render-variants" role="group" aria-label="Mythic avatar version">
        <button
          type="button"
          className={!usesMythicLiveVariantB(presentation.avatarId) ? "active" : ""}
          aria-pressed={!usesMythicLiveVariantB(presentation.avatarId)}
          disabled={busy}
          onClick={() => void run(() => updatePresentation({
            shell: "hud",
            requestedPresence: "particle_bust",
            avatarId: MYTHIC_PORTRAIT_A_AVATAR_ID,
          }))}
        >
          A · portrait cloud
        </button>
        <button
          type="button"
          className={usesMythicLiveVariantB(presentation.avatarId) ? "active" : ""}
          aria-pressed={usesMythicLiveVariantB(presentation.avatarId)}
          disabled={busy}
          onClick={() => void run(() => updatePresentation({
            shell: "hud",
            requestedPresence: "particle_bust",
            avatarId: MYTHIC_LIVE_B_AVATAR_ID,
          }))}
        >
          B · live gaze
        </button>
      </div>
      <div className="named-persona-roster" role="group" aria-label="Named persona avatars">
        {options.map((persona) => {
          const selected = persona.id === (pendingId || active?.id || "anzu")
          const row = state?.personas.find((item) => item.id === persona.id)
          const isDefault = row?.is_default ?? persona.id === (state?.default_id || "anzu")
          const isPinned = row?.is_pinned ?? (state?.pinned_ids || []).includes(persona.id)
          return (
            <div key={persona.id} className={`named-persona-card-wrap${selected ? " active" : ""}`}>
              <button
                type="button"
                className={`named-persona-card${selected ? " active" : ""}`}
                aria-pressed={selected}
                title={persona.role || `${persona.label} persona`}
                onClick={() => void choose(persona.id)}
              >
                <SpecialistShapeMark
                  personaId={persona.id}
                  shapeId={persona.presence_shape_id}
                  color={persona.default_colors.orb}
                  label={`${persona.label} avatar`}
                  size={46}
                />
                <span>{persona.label}</span>
              </button>
              <div className="named-persona-card-actions">
                <button
                  type="button"
                  className={`named-persona-icon-btn${isDefault ? " on" : ""}`}
                  title={isDefault ? "Default persona on startup" : "Make default on startup"}
                  aria-pressed={isDefault}
                  aria-label={isDefault ? "Default persona on startup" : "Make default on startup"}
                  disabled={busy || isDefault}
                  onClick={(event) => {
                    event.stopPropagation()
                    void run(() => updateNamedPersonaPrefs(persona.id, { setAsDefault: true }))
                  }}
                >
                  Default
                </button>
                <button
                  type="button"
                  className={`named-persona-icon-btn${isPinned ? " on" : ""}`}
                  title={isPinned ? "Unpin from HUD bar" : "Pin to HUD bar"}
                  aria-pressed={isPinned}
                  aria-label={isPinned ? "Unpin from HUD bar" : "Pin to HUD bar"}
                  disabled={busy}
                  onClick={(event) => {
                    event.stopPropagation()
                    void run(() => updateNamedPersonaPrefs(persona.id, { pin: !isPinned }))
                  }}
                >
                  Pin
                </button>
              </div>
            </div>
          )
        })}
      </div>
      <p className="settings-note">
        Default sets who loads on startup; Pin puts up to{" "}
        {state?.max_pinned ?? 5} personas on the HUD top bar.
      </p>
      {active?.id && (
        <button
          type="button"
          className="btn secondary"
          disabled={busy || (active.is_default ?? active.id === (state?.default_id || "anzu"))}
          onClick={() => void run(() => updateNamedPersonaPrefs(active.id, { setAsDefault: true }))}
        >
          {(active.is_default ?? active.id === (state?.default_id || "anzu"))
            ? `${active.label} is the default persona`
            : `Make ${active.label} the default`}
        </button>
      )}
      {active?.id && activeVoice && !activeVoice.available && (
        <button type="button" className="btn secondary" disabled={busy} onClick={() => void choose(active.id)}>
          Get {active.label} neural voice
        </button>
      )}
      {progress && <p className="settings-note" role="status">{progress}</p>}
      {pendingId && !progress && (
        <p className="named-persona-switch-status" role="status">
          <span className="named-persona-switch-pulse" aria-hidden="true" />
          Morphing to {PERSONA_LABELS[pendingId] || pendingId}…
        </p>
      )}
      {appearance && active && (
        <div className="named-persona-overrides">
          <label>
            Pitch
            <input
              type="range"
              min={-6}
              max={6}
              step={1}
              disabled={busy}
              value={appearance.pitch}
              aria-label="Persona pitch"
              onChange={(event) => void patch({ pitch: Number(event.target.value) })}
            />
          </label>
          <label>
            Speaking speed
            <input
              type="range"
              min={0.75}
              max={1.35}
              step={0.02}
              disabled={busy}
              value={appearance.speaking_rate}
              aria-label="Persona speaking speed"
              onChange={(event) => void patch({ speaking_rate: Number(event.target.value) })}
            />
          </label>
          <label>
            Volume
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              disabled={busy}
              value={appearance.volume}
              aria-label="Persona volume"
              onChange={(event) => void patch({ volume: Number(event.target.value) })}
            />
          </label>
          <label>
            Orb colour
            <input
              type="color"
              disabled={busy}
              value={(appearance.orb_color || "#9B1B30").toLowerCase()}
              aria-label="Persona orb colour"
              onChange={(event) => void patch({ orb_color: event.target.value })}
            />
          </label>
          <label>
            Accent colour
            <input
              type="color"
              disabled={busy}
              value={(appearance.accent_color || "#D4A017").toLowerCase()}
              aria-label="Persona accent colour"
              onChange={(event) => void patch({ accent_color: event.target.value })}
            />
          </label>
          <label>
            Brightness
            <input
              type="range"
              min={0.35}
              max={1}
              step={0.05}
              disabled={busy}
              value={appearance.glow}
              aria-label="Persona brightness"
              onChange={(event) => void patch({ glow: Number(event.target.value) })}
            />
            <output>{Math.round(appearance.glow * 100)}%</output>
          </label>
          <label>
            Particle detail
            <input
              type="range"
              min={0.35}
              max={1}
              step={0.05}
              disabled={busy}
              value={appearance.detail ?? 0.68}
              aria-label="Persona particle detail"
              onChange={(event) => void patch({ detail: Number(event.target.value) })}
            />
            <output>{Math.round((appearance.detail ?? 0.68) * 100)}%</output>
          </label>
          <label>
            Animation
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              disabled={busy}
              value={appearance.animation}
              aria-label="Persona animation intensity"
              onChange={(event) => void patch({ animation: Number(event.target.value) })}
            />
          </label>
          <label>
            Orb scale
            <input
              type="range"
              min={0.7}
              max={1.4}
              step={0.01}
              disabled={busy}
              value={appearance.scale}
              aria-label="Persona orb scale"
              onChange={(event) => void patch({ scale: Number(event.target.value) })}
            />
          </label>
          {/* RFC-0137 §4 interim hide of the orphaned specialists_auto_speak control.
              Re-enable once the backend specialist-speech acceptance criteria pass. */}
          <button type="button" className="btn secondary" disabled={busy} onClick={() => void run(() => resetNamedPersona(active.id))}>
            Reset persona appearance
          </button>
        </div>
      )}
      {error && <p className="settings-note">{error}</p>}
    </div>
  )
}
