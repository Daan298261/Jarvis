import { useNavigate } from "react-router-dom"
import type { Task } from "../api"

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

  const rows = tasks.slice(0, 32).flatMap((task) => {
    const events = (task.events || []).slice(-3)
    const lines: { key: string; taskId: string; label: string; detail: string; tone: string }[] = []

    lines.push({
      key: `${task.id}-head`,
      taskId: task.id,
      label: taskLabel(task),
      detail: `${task.status}${task.current_tool ? ` · ${task.current_tool}` : ""}`,
      tone: task.status === "failed" ? "bad" : task.status === "running" ? "active" : "muted",
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
          </button>
        ))}
      </div>
    </aside>
  )
}
