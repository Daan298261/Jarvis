import type { Task } from "../api"
import { phaseLabel } from "../taskStatus"

function clock(value?: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

function age(value?: string | null): string {
  if (!value) return "No update yet"
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

export function TaskHeartbeat({ task, label = true }: { task: Task; label?: boolean }) {
  const heartbeat = task.heartbeat_status || (task.alive ? "alive" : "stopped")
  const text = heartbeat === "alive" ? "Live" : heartbeat === "waiting" ? "Waiting" : heartbeat === "stale" ? "Stale" : "Stopped"
  return (
    <span className={`task-heartbeat ${heartbeat}`} title={task.last_heartbeat_at ? `Heartbeat ${age(task.last_heartbeat_at)}` : text}>
      <span className="task-heartbeat-dot" />
      {label && text}
    </span>
  )
}

export function TaskActivityPanel({ task, elapsed }: { task: Task; elapsed: number }) {
  const active = ["queued", "running", "waiting"].includes(task.state || task.status)
  const recent = (task.events || []).slice(-10).reverse()
  const verification = task.verification_summary
  return (
    <details className="task-activity" open={active}>
      <summary>
        <span><TaskHeartbeat task={task} /> · {phaseLabel(task)}</span>
        <span className="task-activity-summary">{task.current_action || "Waiting for activity"}</span>
      </summary>
      <div className="task-activity-grid">
        <div><b>State</b><span>{task.state || task.status}</span></div>
        <div><b>Started</b><span>{clock(task.started_at || task.created_at)}</span></div>
        <div><b>Elapsed</b><span>{elapsed}s</span></div>
        <div><b>Worker</b><span>{task.active_worker || "Jarvis agent"}</span></div>
        <div className="span-2"><b>Current activity</b><span>{task.current_action || task.stage || "Queued"}{task.current_tool ? ` · ${task.current_tool}` : ""}</span></div>
        <div><b>Last progress</b><span>{age(task.last_progress_at)}</span></div>
        <div><b>Heartbeat</b><span>{age(task.last_heartbeat_at)}</span></div>
      </div>
      {recent.length > 0 && (
        <div className="task-recent-actions">
          <b>Recent activity</b>
          {recent.map((event, index) => (
            <div key={`${event.created_at}-${index}`}>
              <span>{clock(event.created_at)}</span>
              <strong>{event.title}</strong>
              <em>{event.source || "jarvis-agent"}</em>
            </div>
          ))}
        </div>
      )}
      {verification && verification.result !== "NOT_VERIFIED" && (
        <div className={`verification-summary ${verification.result.toLowerCase()}`}>
          <b>{verification.result.replaceAll("_", " ")}</b>
          <span>{verification.checks[0] || verification.warnings[0] || "Verification recorded."}</span>
        </div>
      )}
    </details>
  )
}
