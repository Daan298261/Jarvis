import type { PersonaCloudVisual, PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import { MorphablePresenceStage } from "./MorphablePresenceStage"
import "./humanoid-presence.css"

type Props = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
  shapeId?: string
  personaVisual?: PersonaCloudVisual
}

export function ParticleBustPresence({ snapshot, settings, shapeId, personaVisual }: Props) {
  return (
    <MorphablePresenceStage
      snapshot={snapshot}
      settings={settings}
      shapeId={shapeId}
      personaVisual={personaVisual}
      className="jarvis-presence jarvis-presence-humanoid jarvis-presence-particle"
      ariaLabel={`Jarvis particle bust is ${snapshot.phase}`}
    >
      <div className="jarvis-humanoid-label" aria-hidden="true">
        <span>JARVIS</span><i /><span>PARTICLE BUST</span>
      </div>
    </MorphablePresenceStage>
  )
}

export default ParticleBustPresence
