import { useCallback, type CSSProperties } from "react"
import { useNavigate } from "react-router-dom"
import type { ApexSelection } from "../../vendor/apex-ui/ReasoningWeb"
import { MorphablePresenceStage } from "./MorphablePresenceStage"
import { NeuralChrome, neuralSpecialistRoute, type NeuralPresenceProps } from "./neuralChrome"

/** WebGL neural body: the same free→figure orb cloud as every other avatar. */
export function NeuralCloudPresence({
  snapshot,
  settings,
  size = 540,
  shapeId,
  personaVisual,
}: NeuralPresenceProps) {
  const navigate = useNavigate()
  const reduced = settings.reducedMotion === "reduce"
  const onSelect = useCallback((selection: ApexSelection) => {
    const route = neuralSpecialistRoute(selection.key)
    if (route) navigate(route)
  }, [navigate])

  return (
    <MorphablePresenceStage
      snapshot={snapshot}
      settings={settings}
      shapeId={shapeId}
      personaVisual={personaVisual}
      className={`jarvis-presence jarvis-presence-neural jarvis-apex-presence${reduced ? " reduced-motion" : ""}`}
      ariaLabel={`Jarvis is ${snapshot.phase}`}
      transparentBackdrop
      style={{ "--jarvis-apex-size": `${size}px` } as CSSProperties}
    >
      <NeuralChrome snapshot={snapshot} settings={settings} onSelect={onSelect} />
    </MorphablePresenceStage>
  )
}

export default NeuralCloudPresence
