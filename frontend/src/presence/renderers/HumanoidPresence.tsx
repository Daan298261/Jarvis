import { useEffect, useState, type CSSProperties } from "react"
import { galaxyStatusText } from "../galaxyPresence"
import type { PersonaCloudVisual, PresencePhase, PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import { readVoiceMeter } from "../../tts/voiceAnalyser"
import { MorphablePresenceStage } from "./MorphablePresenceStage"
import "./humanoid-presence.css"

type HumanoidPresenceProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
  /** Optional override for harness / morph demos; defaults from settings.avatarId. */
  shapeId?: string
  personaVisual?: PersonaCloudVisual
}

function phaseLabel(phase: PresencePhase): string {
  if (phase === "executing") return "WORKING"
  return phase.toUpperCase()
}

export function HumanoidPresence({ snapshot, settings, shapeId, personaVisual }: HumanoidPresenceProps) {
  const galaxy = settings.requestedPresence === "galaxy"
  const [meter, setMeter] = useState({ level: 0, attached: false })

  useEffect(() => {
    const live = galaxy && (snapshot.phase === "speaking" || snapshot.phase === "listening")
    if (!live) {
      setMeter({ level: 0, attached: false })
      return
    }
    const expected = snapshot.phase === "speaking" ? "tts" : "mic"
    let frame = 0
    let last = 0
    const tick = (time: number) => {
      frame = window.requestAnimationFrame(tick)
      if (time - last < 80) return
      last = time
      const reading = readVoiceMeter()
      const attached = reading.attached && reading.kind === expected
      setMeter({ level: attached ? reading.level : 0, attached })
    }
    frame = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(frame)
  }, [galaxy, snapshot.phase])

  return (
    <MorphablePresenceStage
      snapshot={snapshot}
      settings={settings}
      shapeId={shapeId}
      personaVisual={personaVisual}
      className={`jarvis-presence jarvis-presence-humanoid${galaxy ? " galaxy" : ""}`}
      ariaLabel={`ANZU particle presence is ${snapshot.phase === "executing" ? "working" : snapshot.phase}`}
    >
      {snapshot.phase === "offline" && <span className="jarvis-presence-broken-ring" aria-hidden="true" />}
      {snapshot.phase === "approval" && <span className="jarvis-presence-lock-ring" aria-hidden="true" />}
      {galaxy ? (
        <p
          className="jarvis-galaxy-status"
          role="status"
          style={personaVisual?.accentColor ? { "--galaxy-accent": personaVisual.accentColor } as CSSProperties : undefined}
        >
          {galaxyStatusText(snapshot.phase, {
            analyser: meter.attached,
            level: meter.level,
            bust: true,
          })}
        </p>
      ) : (
        <>
          <div className="jarvis-humanoid-hud" aria-hidden="true">
            <span className="jarvis-humanoid-hud-tl" />
            <span className="jarvis-humanoid-hud-tr">
              TEM // PRESENCE
              <br />
              {phaseLabel(snapshot.phase)}
            </span>
            <span className="jarvis-humanoid-hud-bl" />
          </div>
          <div className="jarvis-humanoid-label" aria-hidden="true">
            <span>ANZU</span><i /><span>NEURAL PRESENCE</span>
          </div>
        </>
      )}
    </MorphablePresenceStage>
  )
}

export default HumanoidPresence
