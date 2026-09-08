/*
 * Jarvis Command Deck: an APEX-UI-derived visual shell connected to Jarvis's
 * existing routes and task/chat engine. APEX-UI is MIT licensed; see
 * frontend/third_party/APEX-UI/.
 */

import { useCallback, useState, type CSSProperties } from "react"
import { NavLink } from "react-router-dom"
import type { Task } from "../api"
import { HudChat } from "../hud/HudChat"
import { deriveOrbMood, type OrbMood } from "../hud/orbMood"
import { AppearancePresenceControls } from "../presence/AppearancePresenceControls"
import { usePresentationSettings } from "../presence/presentationSettings"
import { JarvisOrb, type JarvisOrbState } from "./JarvisOrb"
import "./apex-ui.css"

type Specialist = {
  name: string
  meta: string
  to: string
  x: number
  y: number
  tone: "cyan" | "gold"
}

const SPECIALISTS: Specialist[] = [
  { name: "Orchestrator", meta: "Agents", to: "/agents", x: 13, y: 20, tone: "cyan" },
  { name: "Memory", meta: "Knowledge", to: "/memory", x: 12, y: 36, tone: "cyan" },
  { name: "Research", meta: "Workflows", to: "/workflows", x: 12, y: 52, tone: "cyan" },
  { name: "Context", meta: "Repository", to: "/context", x: 13, y: 68, tone: "cyan" },
  { name: "Advisor", meta: "Strategy", to: "/advisor", x: 17, y: 83, tone: "cyan" },

  { name: "History", meta: "Records", to: "/history", x: 29, y: 12, tone: "cyan" },
  { name: "Trajectories", meta: "Goals", to: "/trajectories", x: 29, y: 27, tone: "cyan" },
  { name: "Delegation", meta: "Workers", to: "/delegation", x: 29, y: 76, tone: "gold" },
  { name: "Phone", meta: "Surface", to: "/phone", x: 29, y: 89, tone: "gold" },

  { name: "Developer", meta: "Coding", to: "/coding", x: 71, y: 12, tone: "gold" },
  { name: "Models", meta: "Router", to: "/model", x: 71, y: 27, tone: "gold" },
  { name: "Tools", meta: "Execution", to: "/tools", x: 71, y: 76, tone: "gold" },

  { name: "Swarm", meta: "Nodes", to: "/swarm", x: 87, y: 20, tone: "gold" },
  { name: "Environments", meta: "Workers", to: "/environments", x: 88, y: 36, tone: "gold" },
  { name: "Packs", meta: "Specialists", to: "/packs", x: 88, y: 52, tone: "gold" },
  { name: "System", meta: "Health", to: "/system", x: 87, y: 68, tone: "gold" },
  { name: "Settings", meta: "Control", to: "/settings", x: 83, y: 83, tone: "gold" },
]

const MOOD_COPY: Record<OrbMood, { label: string; detail: string }> = {
  idle: { label: "Standby", detail: "One core · specialist surfaces ready" },
  listening: { label: "Listening", detail: "Voice input active" },
  thinking: { label: "Processing", detail: "Jarvis is executing the current task" },
  speaking: { label: "Speaking", detail: "Response channel active" },
  alert: { label: "Needs you", detail: "Review or approval required" },
}

function taskDetail(task: Task | null, mood: OrbMood): string {
  if (!task) return MOOD_COPY[mood].detail
  if (task.waiting_for_confirmation) return "Approval required before execution can continue"
  if (task.status === "failed") return task.error || "Task execution needs attention"
  const title = task.title || task.prompt?.slice(0, 62)
  return title ? `${title} · ${task.status}` : MOOD_COPY[mood].detail
}

function moodToOrb(mood: OrbMood): JarvisOrbState {
  if (mood === "alert") return "alert"
  return mood
}

export function JarvisCommandDeck() {
  const presentation = usePresentationSettings()
  const [moodState, setMoodState] = useState<{ recording: boolean; speaking: boolean; task: Task | null }>({
    recording: false,
    speaking: false,
    task: null,
  })

  const onMoodChange = useCallback(
    (next: { recording: boolean; speaking: boolean; task: Task | null }) => setMoodState(next),
    [],
  )

  const mood = deriveOrbMood(moodState.task, {
    recording: moodState.recording,
    speaking: moodState.speaking,
    systemDegraded: moodState.task?.status === "failed" || moodState.task?.waiting_for_confirmation,
  })
  const copy = MOOD_COPY[mood]

  return (
    <div className="jarvis-apex-home">
      <div className="jarvis-apex-kicker" aria-hidden="true">
        <span className="jarvis-apex-kicker-label">Command deck</span>
        <strong>JARVIS</strong>
        <span>ONE CORE · SPECIALIST WORKSPACES</span>
      </div>

      <div className="jarvis-apex-legend" aria-label="Specialist legend">
        <span><i /> Knowledge</span>
        <span><i /> Execution</span>
      </div>

      <section className="jarvis-apex-stage" aria-label="Jarvis specialist command deck">
        <div className="jarvis-reasoning-web">
          <svg className="jarvis-reasoning-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            {SPECIALISTS.map((node) => (
              <line key={node.name} x1="50" y1="47" x2={node.x} y2={node.y} />
            ))}
            <circle cx="50" cy="47" r=".32" />
          </svg>

          {SPECIALISTS.map((node) => (
            <NavLink
              key={node.name}
              to={node.to}
              className={`jarvis-node${node.tone === "gold" ? " jarvis-node-gold" : ""}`}
              style={{ "--x": `${node.x}%`, "--y": `${node.y}%` } as CSSProperties}
              aria-label={`Open ${node.name}: ${node.meta}`}
            >
              <span className="jarvis-node-row">
                <span className="jarvis-node-dot" />
                <span className="jarvis-node-name">{node.name}</span>
              </span>
              <span className="jarvis-node-meta">{node.meta}</span>
            </NavLink>
          ))}
        </div>

        <div className="jarvis-apex-core">
          <JarvisOrb state={moodToOrb(mood)} size={550} />
          <div className={`jarvis-apex-core-caption${mood === "alert" ? " alert" : ""}`} aria-live="polite">
            <strong>{copy.label}</strong>
            <span>·</span>
            <span>{taskDetail(moodState.task, mood)}</span>
          </div>
          <AppearancePresenceControls settings={presentation} />
        </div>
      </section>

      <div className="jarvis-apex-chat">
        <HudChat onMoodChange={onMoodChange} />
      </div>
    </div>
  )
}
