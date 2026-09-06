import { useCallback, useState } from "react"
import { ParticleOrb } from "./ParticleOrb"
import { HudChat } from "./HudChat"
import { deriveOrbMood } from "./orbMood"
import type { Task } from "../api"

export function HudChatHome() {
  const [moodState, setMoodState] = useState<{ recording: boolean; speaking: boolean; task: Task | null }>({
    recording: false,
    speaking: false,
    task: null,
  })

  const onMoodChange = useCallback(
    (opts: { recording: boolean; speaking: boolean; task: Task | null }) => setMoodState(opts),
    [],
  )

  const mood = deriveOrbMood(moodState.task, {
    recording: moodState.recording,
    speaking: moodState.speaking,
    systemDegraded: moodState.task?.status === "failed" || moodState.task?.waiting_for_confirmation,
  })

  return (
    <>
      <div className="hud-orb-stack">
        <div className="hud-rings" aria-hidden>
          <span className="hud-ring hud-ring-1" />
          <span className="hud-ring hud-ring-2" />
          <span className="hud-ring hud-ring-3" />
        </div>
        <ParticleOrb mood={mood} size={380} />
      </div>
      <HudChat onMoodChange={onMoodChange} />
    </>
  )
}
