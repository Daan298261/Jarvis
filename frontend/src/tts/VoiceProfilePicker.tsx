import { useEffect, useState } from "react"
import { api } from "../api"
import {
  installVoiceProfile,
  loadVoiceProfileCatalog,
  previewVoiceProfile,
  setActiveVoiceProfile,
  type VoiceProfile,
  type VoiceProfileCatalog,
} from "./voiceProfiles"

type VoiceEngineStatus = {
  engines?: { kokoro?: boolean; kokoro_weights?: boolean }
  tts?: { backend?: string | null }
}

export function VoiceProfilePicker() {
  const [catalog, setCatalog] = useState<VoiceProfileCatalog | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [previewingId, setPreviewingId] = useState<string | null>(null)
  const [msg, setMsg] = useState("")
  const [kokoroReady, setKokoroReady] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    loadVoiceProfileCatalog()
      .then((next) => {
        if (cancelled) return
        setCatalog(next)
        setActiveId(next.active_voice_profile_id)
      })
      .catch(() => {
        if (cancelled) return
        setCatalog({
          profiles: [],
          active_voice_profile_id: null,
          apiAvailable: false,
          loadMessage: "Could not load voice profiles.",
        })
      })
    api<VoiceEngineStatus>("/api/voice/status")
      .then((status) => {
        if (!cancelled) setKokoroReady(Boolean(status.engines?.kokoro))
      })
      .catch(() => {
        if (!cancelled) setKokoroReady(null)
      })
    return () => { cancelled = true }
  }, [])

  async function selectProfile(profile: VoiceProfile) {
    if (!profile.available || busyId) return
    setBusyId(profile.id)
    setMsg("")
    try {
      const nextId = await setActiveVoiceProfile(profile.id)
      setActiveId(nextId)
      setMsg(`Active voice: ${profile.display_name}`)
    } finally {
      setBusyId(null)
    }
  }

  async function previewProfile(profile: VoiceProfile) {
    if (!profile.available || previewingId) return
    setPreviewingId(profile.id)
    setMsg("")
    const ok = await previewVoiceProfile(profile)
    if (!ok) {
      setMsg("Preview is not available for this voice yet.")
    }
    setPreviewingId(null)
  }

  async function installProfile(profile: VoiceProfile) {
    if (busyId) return
    setBusyId(profile.id)
    setMsg(`Installing ${profile.display_name}…`)
    try {
      const result = await installVoiceProfile(profile.id)
      const next = await loadVoiceProfileCatalog()
      setCatalog(next)
      setActiveId(next.active_voice_profile_id)
      const unlocked = next.profiles.find((item) => item.id === profile.id)
      if (result.installed && unlocked?.available) {
        await setActiveVoiceProfile(profile.id)
        setActiveId(profile.id)
        setMsg(`${profile.display_name} is ready.`)
        try {
          const status = await api<VoiceEngineStatus>("/api/voice/status")
          setKokoroReady(Boolean(status.engines?.kokoro))
        } catch {
          setKokoroReady(null)
        }
      } else {
        setMsg(result.detail || unlocked?.install_hint || "Install finished, but this voice is still unavailable.")
      }
    } catch (err: unknown) {
      setMsg(err instanceof Error ? err.message : "Could not install this voice.")
    } finally {
      setBusyId(null)
    }
  }

  if (!catalog) {
    return <p className="lede" style={{ margin: 0 }}>Loading voice profiles…</p>
  }

  if (!catalog.apiAvailable) {
    return (
      <p className="lede voice-profile-stub" style={{ margin: 0 }}>
        {catalog.loadMessage || "Voice profile catalog is not available yet."}
      </p>
    )
  }

  if (!catalog.profiles.length) {
    return (
      <p className="lede voice-profile-stub" style={{ margin: 0 }}>
        No voice profiles are installed yet. The default butler voice will appear here once packs are available.
      </p>
    )
  }

  return (
    <div className="voice-profile-picker">
      <fieldset className="axis-fieldset">
        <legend>Voice profile</legend>
        <p className="lede" style={{ margin: "0 0 10px" }}>
          Original local voice packs only — archetype labels, never copyrighted character voices.
        </p>
        {kokoroReady === false && (
          <p className="lede voice-profile-msg" style={{ margin: "0 0 10px", fontSize: 13 }}>
            Jarvis is preparing the household voice in the background. Until that finishes, speech
            uses the system voice. You can also click <strong>Install household voice</strong> below.
          </p>
        )}
        <div className="axis-options voice-profile-options" role="radiogroup" aria-label="Voice profile">
          {catalog.profiles.map((profile) => {
            const selected = activeId === profile.id
            const disabled = !profile.available || busyId === profile.id
            const needsHouseholdInstall = kokoroReady === false && profile.id === "butler_original_v1"
            const statusLabel = profile.available
              ? (needsHouseholdInstall ? "Household voice is still installing." : null)
              : (profile.install_hint || humanizeUnavailable(profile.unavailable_reason))
            return (
              <div
                key={profile.id}
                className={`axis-option voice-profile-option${selected ? " selected" : ""}${profile.available ? "" : " unavailable"}`}
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  className="voice-profile-select"
                  disabled={disabled}
                  onClick={() => { void selectProfile(profile) }}
                >
                  <strong>{profile.display_name}</strong>
                  <span>{formatArchetype(profile.archetype)}</span>
                  {statusLabel && <em>{statusLabel}</em>}
                </button>
                <div className="voice-profile-actions">
                {profile.available && (
                  <button
                    type="button"
                    className="btn secondary voice-profile-preview"
                    disabled={previewingId === profile.id}
                    onClick={() => { void previewProfile(profile) }}
                  >
                    {previewingId === profile.id ? "Preview…" : "Preview"}
                  </button>
                )}
                {(!profile.available || (kokoroReady === false && profile.id === "butler_original_v1")) && (
                  <button
                    type="button"
                    className="btn secondary voice-profile-preview"
                    disabled={busyId === profile.id}
                    onClick={() => { void installProfile(profile) }}
                  >
                    {busyId === profile.id
                      ? "Installing…"
                      : (profile.available ? "Install household voice" : "Get this voice")}
                  </button>
                )}
                </div>
              </div>
            )
          })}
        </div>
      </fieldset>
      {msg && <p className="lede voice-profile-msg" style={{ margin: "8px 0 0", fontSize: 13 }}>{msg}</p>}
    </div>
  )
}

function formatArchetype(archetype: string): string {
  return archetype
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function humanizeUnavailable(reason?: string): string {
  if (reason === "install_required") return "Install this pack to use it."
  if (reason === "tts_unavailable") return "No local TTS engine is ready for this pack."
  return reason || "Install or unlock this pack to use it."
}
