import { useEffect, useState } from "react"
import {
  loadVoiceProfileCatalog,
  previewVoiceProfile,
  setActiveVoiceProfile,
  type VoiceProfile,
  type VoiceProfileCatalog,
} from "./voiceProfiles"

export function VoiceProfilePicker() {
  const [catalog, setCatalog] = useState<VoiceProfileCatalog | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [previewingId, setPreviewingId] = useState<string | null>(null)
  const [msg, setMsg] = useState("")

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
        <div className="axis-options voice-profile-options" role="radiogroup" aria-label="Voice profile">
          {catalog.profiles.map((profile) => {
            const selected = activeId === profile.id
            const disabled = !profile.available || busyId === profile.id
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
                  {!profile.available && (
                    <em>{profile.unavailable_reason || "Install or unlock this pack to use it."}</em>
                  )}
                </button>
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
