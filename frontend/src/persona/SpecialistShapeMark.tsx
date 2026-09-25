import { useMemo } from "react"
import { resolvePresenceShape } from "../presence/renderers/shapes/catalog"

type SpecialistShapeMarkProps = {
  shapeId: string
  color: string
  label: string
}

/** Static sample of the persona figure. Not a second presence renderer. */
export function SpecialistShapeMark({ shapeId, color, label }: SpecialistShapeMarkProps) {
  const points = useMemo(() => {
    const orbs = resolvePresenceShape(shapeId).buildFigure(0.35)
    const step = Math.max(1, Math.floor(orbs.length / 64))
    return orbs.filter((_, index) => index % step === 0).slice(0, 64)
  }, [shapeId])

  return (
    <svg
      className="hud-specialist-orb"
      viewBox="-1.6 -1.6 3.2 3.2"
      width={72}
      height={72}
      role="img"
      aria-label={label}
    >
      {points.map((point, index) => (
        <circle
          key={`${shapeId}-${index}`}
          cx={point.x}
          cy={-point.y}
          r={0.04}
          fill={color || "#9B1B30"}
          opacity={0.35 + Math.min(0.65, point.light / 3)}
        />
      ))}
    </svg>
  )
}
