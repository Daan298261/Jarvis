import { NeuralOrb } from "../../hud/NeuralOrb"
import type { OrbMood } from "../../hud/orbMood"
import type { PresenceSnapshot, PresentationSettings } from "../presenceTypes"

function moodForPhase(phase: PresenceSnapshot["phase"]): OrbMood {
  switch (phase) {
    case "listening": return "listening"
    case "speaking": return "speaking"
    case "thinking":
    case "executing": return "thinking"
    case "alert":
    case "offline": return "alert"
    case "waiting":
    case "idle":
    default: return "idle"
  }
}

type NeuralPresenceProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
}

export function NeuralPresence({ snapshot, settings, size = 540 }: NeuralPresenceProps) {
  const mood = moodForPhase(snapshot.phase)
  const reduced = settings.reducedMotion === "reduce"

  return (
    <div
      className={`jarvis-presence jarvis-presence-neural${reduced ? " reduced-motion" : ""}`}
      data-performance-preset={settings.performancePreset}
      data-attention-mode={settings.attentionMode}
      aria-label={`Jarvis is ${snapshot.phase}`}
    >
      <NeuralOrb mood={mood} size={size} />
    </div>
  )
}
