import { HumanoidPresence } from "./HumanoidPresence"
import { NeuralSpecialistNav, type NeuralPresenceProps } from "./neuralChrome"

/** WebGL neural body: the same free→figure orb cloud as every other avatar. */
export function NeuralCloudPresence({
  snapshot,
  settings,
  size = 540,
  shapeId,
  personaVisual,
}: NeuralPresenceProps) {
  return (
    <>
    <HumanoidPresence
      snapshot={snapshot}
      settings={settings}
      shapeId={shapeId || "humanoid_bust"}
      personaVisual={personaVisual}
      size={size}
    />
    <NeuralSpecialistNav />
    </>
  )
}

export default NeuralCloudPresence
