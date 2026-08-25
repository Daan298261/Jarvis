import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { api, type Task } from "../api"

function stamp(iso?: string | null) {
  if (!iso) return "—"
  return iso.replace("T", " ").slice(0, 19)
}

function snippet(text?: string | null) {
  const value = (text || "").trim()
  if (!value) return "—"
  return value.length > 90 ? `${value.slice(0, 90)}…` : value
}

function canContinue(status: string) {
  return !["running", "queued", "waiting"].includes(status)
}

export function HistoryPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<Task[]>([])
  const [busyId, setBusyId] = useState("")

  useEffect(() => {
    api<Task[]>("/api/tasks").then(setTasks).catch(() => undefined)
  }, [])

  async function continueTask(task: Task) {
    setBusyId(task.id)
    try {
      await api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ prompt: "Continue this." }) })
      navigate(`/tasks/${task.id}`)
    } finally {
      setBusyId("")
    }
  }

  return (
    <div>
      <h1>Task history</h1>
      <p className="lede">Reopen a previous task and continue it from saved state.</p>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Created</th>
              <th>Last activity</th>
              <th>Duration</th>
              <th>Worker / backend</th>
              <th>Result</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td><Link to={`/tasks/${task.id}`}>{task.title}</Link></td>
                <td><span className={`badge ${task.status}`}>{task.status}</span></td>
                <td>{stamp(task.created_at)}</td>
                <td>{stamp(task.updated_at || task.finished_at || task.created_at)}</td>
                <td>{Math.round(task.duration_seconds || 0)}s</td>
                <td>{task.selected_worker || task.task_class || "native"}</td>
                <td>{snippet(task.result || task.error)}</td>
                <td>
                  {canContinue(task.status) ? (
                    <button className="btn secondary" disabled={busyId === task.id} onClick={() => continueTask(task)}>
                      {busyId === task.id ? "Continuing…" : "Continue"}
                    </button>
                  ) : (
                    <Link to={`/tasks/${task.id}`}>Open</Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!tasks.length ? <p className="lede">No tasks yet.</p> : null}
      </div>
    </div>
  )
}
