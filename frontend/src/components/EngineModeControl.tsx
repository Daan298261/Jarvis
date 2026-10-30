import { useEffect, useId, useRef, useState } from "react"
import { api } from "../api"
import "./engineMode.css"

type EngineMode = "hybrid" | "model_only" | "reflex_only"
const choices: { value: EngineMode; label: string; detail: string }[] = [
  { value: "hybrid", label: "Model + JEV/Laya", detail: "Model answers with configured JEV/Laya decisions." },
  { value: "model_only", label: "Model only", detail: "Model answers. JEV and Laya are bypassed; permission checks remain active." },
  { value: "reflex_only", label: "JEV/Laya only", detail: "Structured decisions and bounded replies. Generative model calls and autoload are off." },
]

export function EngineModeControl() {
  const groupId = useId()
  const requestRevision = useRef(0)
  const [reload, setReload] = useState(0)
  const [mode, setMode] = useState<EngineMode | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [unconfigured, setUnconfigured] = useState(false)
  useEffect(() => {
    let active = true
    const refresh = () => {
      const revision = ++requestRevision.current
      void api<{ engine_mode?: EngineMode; decision?: { laya_enabled?: boolean; tier?: string } }>("/api/settings")
      .then((settings) => {
        if (!active || revision !== requestRevision.current) return
        setMode(settings.engine_mode || "hybrid")
        setError("")
        setUnconfigured(!settings.decision?.laya_enabled && (!settings.decision?.tier || settings.decision.tier === "local"))
      }).catch(() => { if (active && revision === requestRevision.current) setError("Could not read engine mode.") })
    }
    refresh()
    window.addEventListener("anzu-engine-mode", refresh)
    return () => { active = false; window.removeEventListener("anzu-engine-mode", refresh) }
  }, [reload])

  async function selectMode(next: EngineMode) {
    ++requestRevision.current
    setBusy(true)
    setError("")
    try {
      const saved = await api<{ engine_mode: EngineMode }>("/api/settings", { method: "PUT", body: JSON.stringify({ engine_mode: next }) })
      setMode(saved.engine_mode)
      window.dispatchEvent(new Event("anzu-engine-mode"))
    } catch {
      setError("Could not save engine mode. The previous mode is still selected.")
    } finally {
      setBusy(false)
    }
  }

  return <fieldset className="engine-mode-control" aria-busy={busy}>
    <legend>Engine mode</legend>
    <div className="engine-mode-positions" role="radiogroup" aria-label="Engine mode">
      {choices.map((choice) => <label key={choice.value} className={mode === choice.value ? "selected" : ""}>
        <input type="radio" name={groupId} value={choice.value} checked={mode === choice.value} disabled={busy || mode === null}
          onChange={() => void selectMode(choice.value)} />
        <span>{choice.label}</span>
      </label>)}
    </div>
    <p className="engine-mode-detail" role="status">{busy ? "Saving engine mode…" : choices.find((choice) => choice.value === mode)?.detail || "Reading engine mode…"}</p>
    {mode !== "model_only" && unconfigured && <p className="engine-mode-detail">JEV/Laya is not enabled in decision settings; rules fallback is active.</p>}
    <p className="engine-mode-detail">Uses configured providers. Loaded weights may remain in memory until unloaded.</p>
    {error && <p className="engine-mode-error" role="alert">{error} <button type="button" onClick={() => setReload((value) => value + 1)}>Retry</button></p>}
  </fieldset>
}
