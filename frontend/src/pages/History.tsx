import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api, type Task } from "../api"

export function HistoryPage() {
  const [tasks, setTasks] = useState<Task[]>([])
  useEffect(() => {
    api<Task[]>("/api/tasks").then(setTasks)
  }, [])
  return (
    <div>
      <h1>Task history</h1>
      <p className="lede">Reopen a previous task and continue it from saved state.</p>
      <div className="card">
        <table>
          <thead>
            <tr><th>Title</th><th>Status</th><th>Created</th><th>Duration</th></tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td><Link to={`/tasks/${task.id}`}>{task.title}</Link></td>
                <td><span className={`badge ${task.status}`}>{task.status}</span></td>
                <td>{task.created_at?.replace("T", " ").slice(0, 19)}</td>
                <td>{Math.round(task.duration_seconds || 0)}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
