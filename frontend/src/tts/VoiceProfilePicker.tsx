import { useEffect, useState } from "react"
import { api } from "../api"
import { savePersonaAppearance, useNamedPersonas } from "../persona/namedPersonas"
import {
  installVoiceProfile,
  loadVoiceProfileCatalog,
  previewVoiceProfile,
  setActiveVoiceProfile,
  WINDOWS_NATURAL_VOICE_PROFILE_ID,
  type VoiceProfile,
  type VoiceProfileCatalog,
} from "./voiceProfiles"

type VoiceRuntimeStatus = {
  requested_engine?: string | null
  actual_engine?: string | null
  model?: string
  model_id?: string
  voice?: string
  speaker_ref?: string
  ready?: boolean
  last_error?: string | null
}

type VoiceEngineStatus = {
  engines?: { kokoro?: boolean; kokoro_weights?: boolean; kokoro_runtime?: VoiceRuntimeStatus }
  tts?: VoiceRuntimeStatus & { backend?: string | null }
}

function kokoroRuntime(status: VoiceEngineStatus): VoiceRuntimeStatus | undefined {
  return status.tts?.requested_engine === "kokoro"
    ? status.tts
    : status.engines?.kokoro_runtime
}

export function VoiceProfilePicker() {
  const named = useNamedPersonas()
  const [catalog, setCatalog] = useState<VoiceProfileCatalog | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [previewingId, setPreviewingId] = useState<string | null>(null)
  const [msg, setMsg] = useState("")
  const [kokoroReady, setKokoroReady] = useState<boolean | null>(null)
  const [kokoroStatus, setKokoroStatus] = useState("")

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
        if (cancelled) return
        const runtime = kokoroRuntime(status)
        const ready = runtime?.ready === true
        setKokoroReady(ready)
        if (ready) {
          setKokoroStatus(`${runtime?.model || runtime?.model_id || "Kokoro 82M"} · ${runtime?.voice || runtime?.speaker_ref || "voice"} · READY`)
        } else {
          setKokoroStatus(`Kokoro · FAILED TO LOAD${runtime?.last_error ? ` · ${runtime.last_error}` : ""}`)
        }
      })
      .catch(() => {
        if (!cancelled) setKokoroReady(null)
      })
    return () => { cancelled = true }
  }, [])

  async function selectProfile(profile: VoiceProfile) {
    if (!profile.available || busyId) return
    if (profile.id === WINDOWS_NATURAL_VOICE_PROFILE_ID) {
      setMsg("Named personas keep a neural voice. Windows SAPI is not a persona voice.")
      return
    }
    setBusyId(profile.id)
    setMsg("")
    try {
      const nextId = await setActiveVoiceProfile(profile.id)
      setActiveId(nextId)
      const personaId = named?.active?.id
      if (personaId) {
        try {
          await savePersonaAppearance(personaId, { voice_profile_id: profile.id })
        } catch (err) {
          setMsg(err instanceof Error ? err.message : "Could not store that voice on the persona.")
          return
        }
      }
      setMsg(`Active voice: ${profile.display_name}`)
    } finally {
      setBusyId(null)
    }
  }

  async function previewProfile(profile: VoiceProfile) {
    if (!profile.available || previewingId) return
    setPreviewingId(profile.id)
    setMsg("")
    const result = await previewVoiceProfile(profile)
    if (!result.ok) {
      const engine = profile.id.includes("chatterbox") ? "Chatterbox" : "Kokoro"
      setMsg(result.error?.startsWith("Preview audio was generated")
        ? result.error
        : `${engine} preview failed: ${result.error || "The selected voice could not generate audio."}`)
    } else {
      const model = result.modelId || result.engineId || "unknown engine"
      const voice = result.voiceId || result.profileId || profile.id
      setMsg(`Preview: ${model} · ${voice}`)
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
          const runtime = kokoroRuntime(status)
          const ready = runtime?.ready === true
          setKokoroReady(ready)
          setKokoroStatus(ready
            ? `${runtime?.model || runtime?.model_id || "Kokoro 82M"} · ${runtime?.voice || runtime?.speaker_ref || "voice"} · READY`
            : `Kokoro · FAILED TO LOAD${runtime?.last_error ? ` · ${runtime.last_error}` : ""}`)
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
            {kokoroStatus || "Kokoro · FAILED TO LOAD"}. Speech stays silent if the neural voice
            fails; it will not pretend that SAPI is Kokoro. You can also click
            <strong> Install household voice</strong> below.
          </p>
        )}
        {kokoroReady === true && kokoroStatus && (
          <p className="lede voice-profile-msg" style={{ margin: "0 0 10px", fontSize: 13 }}>
            {kokoroStatus}
          </p>
        )}
        <p className="lede voice-profile-msg" style={{ margin: "0 0 10px", fontSize: 13 }}>
          <strong>Household butler</strong> is the default local Kokoro voice. Windows SAPI is an
          explicit baseline choice. <strong>Household butler (expressive)</strong> can be installed
          here without environment-variable setup.
        </p>
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
