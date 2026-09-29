import { useState } from "react"
import { activateNamedPersona } from "./activateNamedPersona"
import { SpecialistShapeMark } from "./SpecialistShapeMark"
import {
  PERSONA_LABELS,
  PERSONA_VISUALS,
  useNamedPersonas,
} from "./namedPersonas"
import "./named-persona.css"

type PinnedPersonaDockProps = {
  disabled?: boolean
}

export function PinnedPersonaDock({ disabled = false }: PinnedPersonaDockProps) {
  const state = useNamedPersonas()
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState("")
  const pinned = state?.pinned_ids || []
  if (!pinned.length) return null

  const byId = new Map((state?.personas || []).map((persona) => [persona.id, persona]))
  const activeId = state?.active?.id || "anzu"

  async function switchTo(id: string) {
    if (id === activeId || busyId) return
    setBusyId(id)
    setError("")
    try {
      await activateNamedPersona(id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not switch persona.")
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="pinned-persona-dock-wrap">
      <div className="pinned-persona-dock" role="toolbar" aria-label="Pinned personas">
        {pinned.map((id) => {
          const persona = byId.get(id)
          const visuals = PERSONA_VISUALS[id as keyof typeof PERSONA_VISUALS]
          const label = persona?.label || PERSONA_LABELS[id] || id
          const shapeId = persona?.presence_shape_id || visuals?.shapeId || "stormbird"
          const color = persona?.appearance?.orb_color || persona?.default_colors?.orb || visuals?.orbColor || "#9B1B30"
          const selected = id === activeId
          const isBusy = busyId === id
          return (
            <button
              key={id}
              type="button"
              className={`pinned-persona-chip${selected ? " active" : ""}`}
              title={`Switch to ${label}`}
              aria-pressed={selected}
              aria-busy={isBusy}
              disabled={disabled || Boolean(busyId)}
              onClick={() => void switchTo(id)}
            >
              <SpecialistShapeMark shapeId={shapeId} color={color} label={`${label} avatar`} size={28} />
              <span>{label}</span>
            </button>
          )
        })}
      </div>
      {error && (
        <p className="pinned-persona-dock-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
