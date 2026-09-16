import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  loadVoiceProfileCatalog,
  setActiveVoiceProfile,
  type VoiceProfile,
  type VoiceProfileCatalog,
  VOICE_PROFILE_CHANGED_EVENT,
} from "../tts/voiceProfiles"
import { settingsSubmenuPath } from "./settingsSubmenus"

export function VoiceHudCompact() {
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceProfileCatalog | null>(null)
  const [voiceBusy, setVoiceBusy] = useState(false)
  const [switchingToId, setSwitchingToId] = useState<string | null>(null)
  const [activeVoiceId, setActiveVoiceId] = useState<string>("")
  const [message, setMessage] = useState("")

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

  const voiceProfiles = voiceCatalog?.profiles ?? []
  const voiceListDisabled = voiceBusy || !voiceCatalog?.apiAvailable || voiceProfiles.length === 0
  const activeProfile = voiceProfiles.find((profile) => profile.id === activeVoiceId)

  return (
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
          if (!profile.available) {
            return (
              <li key={profile.id} role="presentation">
                <Link
                  to={settingsSubmenuPath("voice")}
                  className="jarvis-presence-voice-option unavailable"
                  role="option"
                  aria-selected={false}
                >
                  <span className="jarvis-presence-voice-option-name">{profile.display_name}</span>
                  <span className="jarvis-presence-voice-option-meta">Install in Settings</span>
                </Link>
              </li>
            )
          }
          return (
            <li key={profile.id} role="presentation">
              <button
                type="button"
                role="option"
                aria-selected={selected}
                disabled={voiceListDisabled}
                className={`jarvis-presence-voice-option${selected ? " active" : ""}${voiceBusy && switchingToId === profile.id ? " pending" : ""}`}
                onClick={() => void onVoiceChange(profile.id)}
              >
                <span className="jarvis-presence-voice-option-name">{profile.display_name}</span>
                {selected && !voiceBusy && <span className="jarvis-presence-voice-check" aria-hidden>✓</span>}
                {voiceBusy && switchingToId === profile.id && (
                  <span className="jarvis-presence-voice-spinner" aria-hidden />
                )}
              </button>
            </li>
          )
        })}
      </ul>
      <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
        <Link to={settingsSubmenuPath("voice")}>Open full Voice settings</Link>
      </p>
      {message && <p className="jarvis-presence-controls-message" role="status">{message}</p>}
    </div>
  )
}
