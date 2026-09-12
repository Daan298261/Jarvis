import { useCallback, useState } from "react"
import { HudChat } from "./HudChat"
import { HudHexStrikeSuite } from "./HudHexStrikeSuite"
import { HEXSTRIKE_SHAPE_ID, useHexStrikeSuiteActive } from "./hexstrikeSuite"
import { deriveOrbMood, type OrbMood } from "./orbMood"
import type { Task } from "../api"
import { AppearancePresenceControls } from "../presence/AppearancePresenceControls"
import { PresenceHost } from "../presence/PresenceHost"
import { derivePresenceSnapshot } from "../presence/presenceState"
import { usePresentationSettings } from "../presence/presentationSettings"

const MOOD_COPY: Record<OrbMood, { label: string; detail: string }> = {
  idle: { label: "Ready", detail: "Local intelligence standing by" },
  listening: { label: "Listening", detail: "Voice input active" },
  thinking: { label: "Thinking", detail: "Jarvis is working on the current task" },
  speaking: { label: "Speaking", detail: "Jarvis is responding" },
  alert: { label: "Attention", detail: "Review or approval is required" },
}

function taskDetail(task: Task | null, mood: OrbMood): string {
  if (!task) return MOOD_COPY[mood].detail
  if (task.waiting_for_confirmation) return "Approval required before execution can continue"
  if (task.status === "failed") return task.error || "The current task needs attention"
  const title = task.title || task.prompt?.slice(0, 72)
  if (title) return `${title} · ${task.status}`
  return MOOD_COPY[mood].detail
}

export function HudChatHome() {
  const presentation = usePresentationSettings()
  const { active: hexStrikeActive } = useHexStrikeSuiteActive()
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
  const snapshot = derivePresenceSnapshot({
    task: moodState.task,
    recording: moodState.recording,
    speaking: moodState.speaking,
    systemDegraded: moodState.task?.status === "failed" || !!moodState.task?.waiting_for_confirmation,
  })
  const copy = MOOD_COPY[mood]
  const presenceSettings = hexStrikeActive
    ? { ...presentation, requestedPresence: "humanoid" as const }
    : presentation

  return (
    <div className={`hud-home${hexStrikeActive ? " hexstrike-active" : ""}`}>
      <section className="hud-orb-zone" aria-label="Jarvis state">
        <PresenceHost
          snapshot={snapshot}
          settings={presenceSettings}
          size={760}
          shapeId={hexStrikeActive ? HEXSTRIKE_SHAPE_ID : undefined}
        />
        <div className="hud-orb-caption" aria-live="polite">
          <span className={`hud-orb-state${mood === "alert" ? " alert" : ""}`}>
            {hexStrikeActive ? "Aegis" : copy.label}
          </span>
          <span className="hud-orb-detail">
            {hexStrikeActive ? "HexStrike cybersecurity suite" : taskDetail(moodState.task, mood)}
          </span>
        </div>
        {!hexStrikeActive && <AppearancePresenceControls settings={presentation} />}
      </section>
      {hexStrikeActive && <HudHexStrikeSuite />}
      <HudChat onMoodChange={onMoodChange} />
    </div>
  )
}
