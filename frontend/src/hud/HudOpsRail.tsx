import { useNavigate } from "react-router-dom"
import type { Task } from "../api"
import { SpecialistShapeMark } from "../persona/SpecialistShapeMark"
import { personaCardSentence, useNamedPersonas } from "../persona/namedPersonas"
import "../persona/named-persona.css"

function taskLabel(task: Task): string {
  return task.title || task.prompt?.slice(0, 72) || "Untitled task"
}

function formatTime(iso?: string): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
  } catch {
    return ""
  }
}

type HudOpsRailProps = {
  tasks: Task[]
  activeTaskId?: string
}

export function HudOpsRail({ tasks, activeTaskId }: HudOpsRailProps) {
  const navigate = useNavigate()
  const named = useNamedPersonas()
  const byId = new Map((named?.personas || []).map((persona) => [persona.id, persona]))
  const mainId = named?.active?.id || "anzu"

  const rows = tasks.slice(0, 32).flatMap((task) => {
    const events = (task.events || []).slice(-3)
    const specialists = task.specialist_persona_ids || []
    const sentence = task.persona_card_sentence || personaCardSentence(mainId, specialists)
    const lines: {
      key: string
      taskId: string
      label: string
      detail: string
      tone: string
      sentence?: string
      marks?: { id: string; shapeId: string; color: string; label: string }[]
    }[] = []

    lines.push({
      key: `${task.id}-head`,
      taskId: task.id,
      label: taskLabel(task),
      detail: `${task.status}${task.current_tool ? ` · ${task.current_tool}` : ""}`,
      tone: task.status === "failed" ? "bad" : task.status === "running" ? "active" : "muted",
      sentence: sentence || undefined,
      marks: specialists.map((id) => {
        const persona = byId.get(id)
        return {
          id,
          shapeId: persona?.presence_shape_id || "stormbird",
          color: persona?.appearance.orb_color || persona?.default_colors.orb || "#9B1B30",
          label: persona?.label || id,
        }
      }),
    })

    for (const event of events) {
      lines.push({
        key: `${task.id}-${event.created_at}-${event.title}`,
        taskId: task.id,
        label: event.title,
        detail: `${formatTime(event.created_at)}${event.detail ? ` · ${event.detail.slice(0, 80)}` : ""}`,
        tone: event.kind === "error" ? "bad" : "muted",
      })
    }
    return lines
  })

  return (
    <aside className="hud-rail hud-rail-left" aria-label="Operations log">
      <div className="hud-rail-head">OPS / ACTIVITY</div>
      <div className="hud-log">
        {rows.length === 0 && <p className="hud-log-empty">No recent tasks. Start from the composer.</p>}
        {rows.map((row) => (
          <button
            key={row.key}
            type="button"
            className={`hud-log-row${row.taskId === activeTaskId ? " active" : ""} tone-${row.tone}`}
            onClick={() => navigate(`/tasks/${row.taskId}`)}
          >
            <span className="hud-log-label">{row.label}</span>
            <span className="hud-log-detail">{row.detail}</span>
            {!!row.marks?.length && (
              <span className="hud-specialist-row">
                {row.marks.map((mark) => (
                  <SpecialistShapeMark key={mark.id} shapeId={mark.shapeId} color={mark.color} label={mark.label} />
                ))}
              </span>
            )}
            {row.sentence && <span className="hud-log-detail hud-persona-sentence">{row.sentence}</span>}
          </button>
        ))}
      </div>
    </aside>
  )
}
