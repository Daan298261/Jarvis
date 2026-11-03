import { useEffect, useId, useRef, useState } from "react"
import { api, isApiError } from "../api"
import { failureNote, releaseNote, type ReleaseNote, type ReleaseResult } from "./modelRelease"
import "./modelRelease.css"

type SettingsPayload = { inference?: { keep_warm?: boolean } }

/** Top-right HUD controls: one-click Unload model and the persisted Keep warm switch. */
export function HudModelRelease() {
  const noteId = useId(), mounted = useRef(true)
  const [keepWarm, setKeepWarm] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false), [saving, setSaving] = useState(false)
  const [note, setNote] = useState<ReleaseNote | null>(null)

  useEffect(() => {
    mounted.current = true
    void api<SettingsPayload>("/api/settings").then(
      (settings) => { if (mounted.current) setKeepWarm(Boolean(settings.inference?.keep_warm)) },
      () => { if (mounted.current) setNote({ tone: "error", text: "Keep warm could not be read; the setting is unchanged." }) })
    return () => { mounted.current = false }
  }, [])

  const unload = async () => {
    if (busy) return
    setBusy(true); setNote(null)
    try {
      const result = await api<ReleaseResult>("/api/model/unload-all", { method: "POST" })
      if (mounted.current) setNote(releaseNote(result))
    } catch (error) {
      if (mounted.current) setNote(failureNote(isApiError(error) ? error.status : undefined, error instanceof Error ? error.message : ""))
    } finally {
      if (mounted.current) setBusy(false)
    }
  }

  const toggleWarm = async () => {
    if (saving || keepWarm === null) return
    const next = !keepWarm
    setSaving(true); setNote(null)
    try {
      const saved = await api<SettingsPayload>("/api/settings", { method: "PUT", body: JSON.stringify({ inference_keep_warm: next }) })
      if (mounted.current) setKeepWarm(Boolean(saved.inference?.keep_warm))
    } catch (error) {
      if (mounted.current) setNote({ tone: "error", text: `Keep warm was not saved: ${error instanceof Error ? error.message : "the backend refused it."}` })
    } finally {
      if (mounted.current) setSaving(false)
    }
  }

  return (
    <div className="hud-model-release">
      <button type="button" className={`hud-icon-btn hud-unload-btn${busy ? " busy" : ""}`} onClick={() => void unload()} disabled={busy}
        aria-busy={busy} aria-describedby={note ? noteId : undefined}
        title="Unload every model ANZU has loaded (Ollama, LM Studio, llama-server)">
        {busy ? "Unloading…" : "Unload model"}
      </button>
      <button type="button" role="switch" className={`hud-icon-btn hud-keep-warm${keepWarm ? " on" : ""}`} aria-checked={Boolean(keepWarm)}
        onClick={() => void toggleWarm()} disabled={saving || keepWarm === null}
        title={keepWarm ? "Models stay loaded" : "Models unload after 5 minutes without a turn"}>
        Keep warm: {keepWarm === null ? "…" : keepWarm ? "On" : "Off"}
      </button>
      {note && <p id={noteId} role="status" className={`hud-model-release-note ${note.tone}`}>{note.text}</p>}
    </div>
  )
}
