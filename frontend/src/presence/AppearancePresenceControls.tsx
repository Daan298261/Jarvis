import { useEffect, useState } from "react"
import {
  loadVoiceProfileCatalog,
  setActiveVoiceProfile,
  type VoiceProfile,
  type VoiceProfileCatalog,
  VOICE_PROFILE_CHANGED_EVENT,
} from "../tts/voiceProfiles"
import { updatePresentation } from "./presentationSettings"
import type { PresentationSettings } from "./presenceTypes"

type AppearancePresenceControlsProps = {
  settings: PresentationSettings
}

export function AppearancePresenceControls({ settings }: AppearancePresenceControlsProps) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceProfileCatalog | null>(null)
  const [voiceBusy, setVoiceBusy] = useState(false)
  const [switchingToId, setSwitchingToId] = useState<string | null>(null)
  const [activeVoiceId, setActiveVoiceId] = useState<string>("")

  useEffect(() => {
    let cancelled = false
    loadVoiceProfileCatalog()
      .then((catalog) => {
        if (cancelled) return
        setVoiceCatalog(catalog)
        setActiveVoiceId(catalog.active_voice_profile_id || "")
      })
      .catch(() => {
        if (!cancelled) setVoiceCatalog(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const onVoiceChanged = (event: Event) => {
      const custom = event as CustomEvent<string | null>
      setActiveVoiceId(custom.detail || "")
    }
    window.addEventListener(VOICE_PROFILE_CHANGED_EVENT, onVoiceChanged)
    return () => window.removeEventListener(VOICE_PROFILE_CHANGED_EVENT, onVoiceChanged)
  }, [])

  async function onVoiceChange(profileId: string) {
    const id = profileId.trim()
    if (!id || id === activeVoiceId || voiceBusy) return
    const profile = voiceCatalog?.profiles.find((item) => item.id === id)
    if (!profile?.available) return
    setVoiceBusy(true)
    setSwitchingToId(id)
    setMessage("Switching voice…")
    try {
      const next = await setActiveVoiceProfile(id)
      setActiveVoiceId(next || id)
      const refreshed = await loadVoiceProfileCatalog()
      setVoiceCatalog(refreshed)
      setActiveVoiceId(refreshed.active_voice_profile_id || next || id)
      setMessage(profile ? `Active: ${profile.display_name}` : "Voice profile updated.")
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not change voice profile.")
    } finally {
      setVoiceBusy(false)
      setSwitchingToId(null)
    }
  }

  async function apply(patch: Partial<PresentationSettings>, note = "") {
    setBusy(true)
    setMessage("")
    try {
      await updatePresentation(patch)
      setMessage(note)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save presentation settings.")
    } finally {
      setBusy(false)
    }
  }

  const selected = settings.shell === "classic" ? "classic" : settings.requestedPresence
  const voiceProfiles = voiceCatalog?.profiles ?? []
  const voiceListDisabled = voiceBusy || !voiceCatalog?.apiAvailable || voiceProfiles.length === 0
  const activeProfile = voiceProfiles.find((profile) => profile.id === activeVoiceId)

  return (
    <details className="jarvis-presence-controls">
      <summary>Appearance &amp; voice</summary>
      <div className="jarvis-presence-controls-body">
        <div className="jarvis-presence-voice-row">
          <span className="jarvis-presence-voice-label">Voice (TTS)</span>
          {activeProfile && (
            <span className="jarvis-presence-voice-active" aria-live="polite">
              {voiceBusy ? "Switching…" : `Active: ${activeProfile.display_name}`}
            </span>
          )}
          {!voiceCatalog?.apiAvailable && (
            <p className="jarvis-presence-voice-hint">{voiceCatalog?.loadMessage ?? "Voice catalog unavailable."}</p>
          )}
          <ul
            className={`jarvis-presence-voice-list${voiceBusy ? " switching" : ""}`}
            role="listbox"
            aria-label="Voice profile"
            aria-busy={voiceBusy}
          >
            {voiceProfiles.map((profile: VoiceProfile) => {
              const selected = profile.id === activeVoiceId
              return (
                <li key={profile.id} role="presentation">
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    disabled={voiceListDisabled || !profile.available}
                    className={`jarvis-presence-voice-option${selected ? " active" : ""}${voiceBusy && switchingToId === profile.id ? " pending" : ""}`}
                    onClick={() => void onVoiceChange(profile.id)}
                  >
                    <span className="jarvis-presence-voice-option-name">{profile.display_name}</span>
                    {!profile.available && (
                      <span className="jarvis-presence-voice-option-meta">Install in Settings</span>
                    )}
                    {selected && !voiceBusy && <span className="jarvis-presence-voice-check" aria-hidden>✓</span>}
                    {voiceBusy && switchingToId === profile.id && (
                      <span className="jarvis-presence-voice-spinner" aria-hidden />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>

        <div className="jarvis-presence-mode-row" role="group" aria-label="Jarvis interface">
          <button type="button" disabled={busy} className={selected === "classic" ? "active" : ""}
            onClick={() => apply({ shell: "classic", requestedPresence: "none" })}>
            Classic
          </button>
          <button type="button" disabled={busy} className={selected === "neural" ? "active" : ""}
            onClick={() => apply({ shell: "hud", requestedPresence: "neural" })}>
            Neural HUD
          </button>
          <button type="button" disabled={busy} className={selected === "humanoid" ? "active" : ""}
            onClick={() => apply(
              { shell: "hud", requestedPresence: "humanoid" },
              "Humanoid presence active. Jarvis will fall back to Neural if WebGL is unavailable.",
            )}>
            Humanoid HUD · built in
          </button>
          <button type="button" disabled={busy} className={selected === "particle_bust" ? "active" : ""}
            onClick={() => apply(
              { shell: "hud", requestedPresence: "particle_bust" },
              "Particle bust active. Jarvis will fall back to Neural if WebGL is unavailable.",
            )}>
            Particle bust · experimental
          </button>
        </div>

        <label>
          Rendering
          <select disabled={busy} value={settings.performancePreset}
            onChange={(event) => apply({ performancePreset: event.target.value as PresentationSettings["performancePreset"] })}>
            <option value="auto">Auto</option>
            <option value="efficient">Efficient</option>
            <option value="balanced">Balanced</option>
            <option value="cinematic">Cinematic</option>
          </select>
        </label>

        <label>
          Attention
          <select disabled={busy} value={settings.attentionMode}
            onChange={(event) => apply(
              { attentionMode: event.target.value as PresentationSettings["attentionMode"] },
              event.target.value === "camera" ? "Camera preference saved. RFC-0050 does not activate a camera." : "",
            )}>
            <option value="off">Off</option>
            <option value="pointer">Follow pointer</option>
            <option value="camera">Camera preference (not activated here)</option>
          </select>
        </label>

        <label>
          Motion
          <select disabled={busy} value={settings.reducedMotion}
            onChange={(event) => apply({ reducedMotion: event.target.value as PresentationSettings["reducedMotion"] })}>
            <option value="system">Follow system</option>
            <option value="reduce">Reduce motion</option>
            <option value="full">Full motion</option>
          </select>
        </label>

        {message && <p className="jarvis-presence-controls-message" role="status">{message}</p>}
      </div>
    </details>
  )
}
