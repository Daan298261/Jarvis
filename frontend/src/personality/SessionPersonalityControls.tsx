import { useEffect, useState } from "react"
import { api } from "../api"
import { applySessionTheme, refreshSessionPersonality, type SessionMode } from "../hud/sessionPersonality"

export function SessionPersonalityControls() {
  const [modes, setModes] = useState<SessionMode[]>([])
  const [activeId, setActiveId] = useState("core")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const payload = await api<{ active: SessionMode; modes: SessionMode[] }>("/api/session-personality")
        if (cancelled) return
        setModes(payload.modes || [])
        setActiveId(payload.active?.id || "core")
        applySessionTheme(payload.active)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load personalities")
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  async function selectMode(modeId: string) {
    setBusy(true)
    setError("")
    try {
      const payload = await api<{ active: SessionMode }>("/api/session-personality", {
        method: "PUT",
        body: JSON.stringify({ mode: modeId }),
      })
      setActiveId(payload.active.id)
      applySessionTheme(payload.active)
      await refreshSessionPersonality()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not switch personality")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="session-personality-controls">
      <label>
        Session personality
        <select
          disabled={busy || modes.length === 0}
          value={activeId}
          aria-label="Session personality"
          onChange={(event) => void selectMode(event.target.value)}
        >
          {modes.map((mode) => (
            <option key={mode.id} value={mode.id}>
              {mode.label}
            </option>
          ))}
        </select>
      </label>
      {error && <p className="settings-note">{error}</p>}
      <p className="settings-note">
        Say “start a coding session” in chat, or pick a mode here. HUD accents update; full presence reskin is not in
        scope.
      </p>
    </div>
  )
}
