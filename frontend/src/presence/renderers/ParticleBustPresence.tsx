import { useEffect, useState } from "react"
import type { PersonaCloudVisual, PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import { MorphablePresenceStage } from "./MorphablePresenceStage"
import { preparePortraitCloud } from "./shapes/portraitCloud"
import "./humanoid-presence.css"

type Props = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
  shapeId?: string
  personaVisual?: PersonaCloudVisual
}

export function ParticleBustPresence({ snapshot, settings, shapeId, personaVisual }: Props) {
  const [prepared, setPrepared] = useState<string>()
  const [preparing, setPreparing] = useState(false)
  const [prepareError, setPrepareError] = useState(false)
  useEffect(() => {
    let cancelled = false
    if (!personaVisual?.portraitUrl) return
    setPreparing(true)
    setPrepareError(false)
    preparePortraitCloud(personaVisual.portraitUrl, personaVisual.personaId || "anzu")
      .then((id) => { if (!cancelled) setPrepared(id) })
      .catch(() => { if (!cancelled) setPrepareError(true) })
      .finally(() => { if (!cancelled) setPreparing(false) })
    return () => { cancelled = true }
  }, [personaVisual?.portraitUrl, personaVisual?.personaId])
  return (
    <MorphablePresenceStage
      snapshot={snapshot}
      settings={settings}
      shapeId={personaVisual?.portraitUrl ? prepared || shapeId : shapeId}
      personaVisual={personaVisual}
      className="jarvis-presence jarvis-presence-stage jarvis-presence-humanoid jarvis-presence-particle"
      ariaLabel={`${personaVisual?.personaLabel || "Jarvis"} mythic persona presence is ${snapshot.phase}`}
    >
      {preparing && <span className="jarvis-presence-fallback-note" role="status">Forming {personaVisual?.personaLabel || "avatar"}…</span>}
      {prepareError && <span className="jarvis-presence-fallback-note" role="status">Avatar artwork unavailable · showing particle silhouette</span>}
      <div className="jarvis-humanoid-label" aria-hidden="true">
        <span>{(personaVisual?.personaLabel || "ANZU").toUpperCase()}</span><i /><span>MYTHIC PRESENCE</span>
      </div>
    </MorphablePresenceStage>
  )
}

export default ParticleBustPresence
