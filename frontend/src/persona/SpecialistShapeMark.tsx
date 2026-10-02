import { personaPortraitForId } from "./personaPortraits"

type SpecialistShapeMarkProps = {
  personaId?: string
  shapeId: string
  color: string
  label: string
  size?: number
}

/** Fast, authored character portraits; the live cloud remains the shared renderer. */
export function SpecialistShapeMark({ personaId, shapeId, color, label, size = 72 }: SpecialistShapeMarkProps) {
  const portrait = personaPortraitForId(personaId || "anzu")
  return (
    <span
      className="hud-specialist-orb mythic-persona-mark"
      data-persona={personaId || "anzu"}
      data-shape={shapeId}
      role="img"
      aria-label={label}
      style={{ width: size, height: size, color: color || "#67dcff" }}
    >
      <img src={portrait} alt="" decoding="async" draggable={false} />
    </span>
  )
}
