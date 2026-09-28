import { useEffect, useState } from "react"
import { isApiError } from "../api"
import { installVoiceProfile, loadVoiceProfileCatalog, type VoiceProfileCatalog } from "../tts/voiceProfiles"
import {
  PERSONA_LABELS,
  resetNamedPersona,
  ROSTER_IDS,
  savePersonaAppearance,
  selectNamedPersona,
  useNamedPersonas,
  type PersonaAppearance,
} from "./namedPersonas"
import "./named-persona.css"

const SYSTEM_VOICE = "windows_natural_en_v1"

export function NamedPersonaControls() {
  const state = useNamedPersonas()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [progress, setProgress] = useState("")
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceProfileCatalog | null>(null)
  const active = state?.active
  const appearance = active?.appearance
  const options = state?.personas?.length
    ? state.personas
    : ROSTER_IDS.map((id) => ({ id, label: PERSONA_LABELS[id] || id }))

  useEffect(() => {
    let cancelled = false
    void loadVoiceProfileCatalog().then((catalog) => {
      if (!cancelled) setVoiceCatalog(catalog)
    })
    return () => { cancelled = true }
  }, [])

  async function choose(id: string) {
    setBusy(true)
    setPendingId(id)
    setError("")
    setProgress("")
    try {
      try {
        await selectNamedPersona(id)
      } catch (err) {
        if (!isApiError(err) || err.status !== 409) throw err
        const detail = (err.body as { detail?: { error?: string; profile_id?: string } } | null)?.detail
        if (detail?.error !== "install_required" && detail?.error !== "tts_unavailable") throw err
        const profileId = detail.profile_id
        if (!profileId) throw err
        setProgress(`Downloading the neural voice for ${PERSONA_LABELS[id] || id}…`)
        const result = await installVoiceProfile(profileId)
        if (!result.installed) throw new Error(result.detail || `Could not install ${profileId}.`)
        await selectNamedPersona(id)
      }
      setVoiceCatalog(await loadVoiceProfileCatalog())
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the named persona.")
    } finally {
      setPendingId(null)
      setProgress("")
      setBusy(false)
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
    await run(() => savePersonaAppearance(active.id, partial))
  }

  return (
    <div className="named-persona-controls">
      <label>
        Named persona
        <select
          aria-label="Named persona"
          disabled={busy}
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
      <p className="settings-note">Shape and voice travel together.</p>
      {active?.id && activeVoice && !activeVoice.available && (
        <button type="button" className="btn secondary" disabled={busy} onClick={() => void choose(active.id)}>
          Get {active.label} neural voice
        </button>
      )}
      {progress && <p className="settings-note" role="status">{progress}</p>}
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
            Glow
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              disabled={busy}
              value={appearance.glow}
              aria-label="Persona glow"
              onChange={(event) => void patch({ glow: Number(event.target.value) })}
            />
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
          <label className="named-persona-check">
            <input
              type="checkbox"
              disabled={busy}
              checked={appearance.specialists_auto_speak}
              onChange={(event) => void patch({ specialists_auto_speak: event.target.checked })}
            />
            Specialists speak with their own voice
          </label>
          <button type="button" className="btn secondary" disabled={busy} onClick={() => void run(() => resetNamedPersona(active.id))}>
            Reset persona appearance
          </button>
        </div>
      )}
      {error && <p className="settings-note">{error}</p>}
    </div>
  )
}
