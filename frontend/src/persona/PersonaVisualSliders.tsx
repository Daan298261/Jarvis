import { useState } from "react"
import { savePersonaAppearance, useNamedPersonas } from "./namedPersonas"
import "./named-persona.css"

/** The same persistent controls in Persona and the HUD Appearance menu. */
export function PersonaVisualSliders() {
  const state = useNamedPersonas()
  const [error, setError] = useState("")
  const active = state?.active
  if (!active) return null
  async function patch(key: "glow" | "detail", value: number) {
    if (!active) return
    setError("")
    try {
      await savePersonaAppearance(active.id, { [key]: value })
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return
      setError(err instanceof Error ? err.message : "Could not save avatar appearance.")
    }
  }
  return (
    <div className="named-persona-visual-sliders">
      {([ ["glow", "Brightness", active.appearance.glow],
        ["detail", "Density", active.appearance.detail ?? 0.68] ] as const).map(([key, label, value]) => (
        <label key={key}>
          {label}
          <input type="range" min={0.35} max={1} step={0.01}
            aria-label={`Persona ${label.toLowerCase()}`} value={value}
            onChange={(event) => void patch(key, Number(event.target.value))} />
          <output>{Math.round(value * 100)}%</output>
        </label>
      ))}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}
