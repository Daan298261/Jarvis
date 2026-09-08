import { useCallback, type CSSProperties } from "react"
import { NavLink, useNavigate } from "react-router-dom"
import type { PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import ApexOrb, { type ApexOrbState } from "../../vendor/apex-ui/ApexOrb"
import ReasoningWeb, {
  type ApexRosterEntry,
  type ApexSelection,
} from "../../vendor/apex-ui/ReasoningWeb"
import "../../vendor/apex-ui/apex-orb.css"
import "./apex-presence.css"

type Specialist = {
  key: string
  label: string
  route: string
  roster: ApexRosterEntry
}

// RFC-0058 benchmark roster. A solid node means a credible Jarvis surface exists;
// dashed nodes are parity targets and deliberately do not imply backend parity.
const SPECIALISTS: Specialist[] = [
  { key: "chief_of_staff", label: "Chief of staff", route: "/agents", roster: ["chief_of_staff", "Chief of staff", "consultant", 250, 212, true, 18, 9] },
  { key: "memory", label: "Memory", route: "/memory", roster: ["memory", "Memory", "consultant", 452, 250, true, -18, 8] },
  { key: "strategist", label: "Strategist", route: "/advisor", roster: ["strategist", "Strategist", "consultant", 296, 118, true, -22, 6.5] },
  { key: "researcher", label: "Researcher", route: "/workflows", roster: ["researcher", "Researcher", "consultant", 182, 150, true, 24, 6.5] },
  { key: "finance", label: "Finance", route: "/packs", roster: ["finance", "Finance", "consultant", 436, 148, false, -20, 6.5] },
  { key: "editor", label: "Editor", route: "/workflows", roster: ["editor", "Editor", "consultant", 584, 208, false, -26, 6.5] },
  { key: "sales", label: "Sales", route: "/packs", roster: ["sales", "Sales", "doer", 158, 266, false, 22, 6.5] },
  { key: "ops", label: "Ops", route: "/delegation", roster: ["ops", "Ops", "doer", 232, 330, true, 20, 6.5] },
  { key: "social_media", label: "Social", route: "/packs", roster: ["social_media", "Social", "doer", 330, 374, false, -16, 6.5] },
  { key: "engineering", label: "Engineering", route: "/packs", roster: ["engineering", "Engineering", "doer", 426, 350, false, -18, 6.5] },
  { key: "design", label: "Design", route: "/packs", roster: ["design", "Design", "doer", 502, 312, false, -22, 6.5] },
  { key: "developer", label: "Developer", route: "/coding", roster: ["developer", "Developer", "doer", 118, 356, true, 26, 6] },
  { key: "analytics", label: "Analytics", route: "/trajectories", roster: ["analytics", "Analytics", "tool", 256, 388, false, 20, 5.5] },
  { key: "crm", label: "CRM", route: "/packs", roster: ["crm", "CRM", "tool", 414, 392, false, -18, 5.5] },
  { key: "calendar", label: "Calendar", route: "/workflows", roster: ["calendar", "Calendar", "tool", 560, 356, false, -24, 5.5] },
  { key: "email", label: "Email", route: "/workflows", roster: ["email", "Email", "tool", 608, 286, false, -26, 5.5] },
  { key: "drive", label: "Drive", route: "/context", roster: ["drive", "Drive", "tool", 582, 132, false, 24, 5.5] },
]

const ROSTER = SPECIALISTS.map((specialist) => specialist.roster)
const ROUTES = new Map(SPECIALISTS.map((specialist) => [specialist.key, specialist.route]))

function orbState(phase: PresenceSnapshot["phase"]): ApexOrbState {
  switch (phase) {
    case "listening": return "listening"
    case "speaking": return "speaking"
    case "thinking":
    case "executing":
    case "alert": return "thinking"
    case "offline":
    case "waiting":
    case "idle":
    default: return "idle"
  }
}

function reasoningState(phase: PresenceSnapshot["phase"]): "standby" | "listening" | "processing" | "speaking" {
  switch (phase) {
    case "listening": return "listening"
    case "speaking": return "speaking"
    case "thinking":
    case "executing":
    case "alert": return "processing"
    case "offline":
    case "waiting":
    case "idle":
    default: return "standby"
  }
}

type NeuralPresenceProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
}

export function NeuralPresence({ snapshot, settings, size = 540 }: NeuralPresenceProps) {
  const navigate = useNavigate()
  const reduced = settings.reducedMotion === "reduce"
  const efficient = settings.performancePreset === "efficient"
  const showReasoningWeb = !reduced && !efficient

  const onSelect = useCallback((selection: ApexSelection) => {
    const route = ROUTES.get(selection.key)
    if (route) navigate(route)
  }, [navigate])

  return (
    <div
      className={`jarvis-presence jarvis-presence-neural jarvis-apex-presence${reduced ? " reduced-motion" : ""}`}
      data-performance-preset={settings.performancePreset}
      data-attention-mode={settings.attentionMode}
      data-phase={snapshot.phase}
      aria-label={`Jarvis is ${snapshot.phase}`}
      style={{ "--jarvis-apex-size": `${size}px` } as CSSProperties}
    >
      {showReasoningWeb && (
        <div className="jarvis-apex-reasoning-web" aria-hidden="true">
          <ReasoningWeb
            state={reasoningState(snapshot.phase)}
            mode="full"
            coreless
            traces={settings.performancePreset === "cinematic" || settings.performancePreset === "auto"}
            roster={ROSTER}
            onSelect={onSelect}
          />
        </div>
      )}

      <div className="jarvis-apex-vendored-orb" aria-hidden="true">
        <ApexOrb state={orbState(snapshot.phase)} />
      </div>

      <div className="jarvis-apex-presence-legend" aria-hidden="true">
        <span><i /> Available</span>
        <span><i className="target" /> Parity target</span>
      </div>

      <nav className="jarvis-apex-sr-nav" aria-label="Jarvis specialist workspaces">
        {SPECIALISTS.map((specialist) => (
          <NavLink key={specialist.key} to={specialist.route}>
            {specialist.label}{specialist.roster[5] ? "" : " (parity target)"}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
