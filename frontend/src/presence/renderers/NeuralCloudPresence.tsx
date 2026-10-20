import { lazy, Suspense } from "react"
import { PresenceFallback } from "../PresenceFallback"
const HumanoidPresence = lazy(() => import("./HumanoidPresence"))
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
    <Suspense fallback={<PresenceFallback snapshot={snapshot} />}><HumanoidPresence
      snapshot={snapshot}
      settings={settings}
      shapeId={shapeId || "humanoid_bust"}
      personaVisual={personaVisual}
      size={size}
    /></Suspense>
    <NeuralSpecialistNav />
    </>
  )
}

export default NeuralCloudPresence
