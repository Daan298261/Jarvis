import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api, type Task } from "../api"
import { TaskHeartbeat } from "../components/TaskActivity"
import { phaseLabel } from "../taskStatus"

export function HistoryPage() {
  const [tasks, setTasks] = useState<Task[]>([])
  useEffect(() => {
    const load = () => api<Task[]>("/api/tasks").then(setTasks)
    void load()
    const timer = window.setInterval(() => void load(), 4000)
    return () => window.clearInterval(timer)
  }, [])
  return (
    <div>
      <h1>Task history</h1>
      <p className="lede">Every past task. Recents in the left rail open the same chats.</p>
      <div className="card">
        <table>
          <thead>
            <tr><th>Title</th><th>State</th><th>Current activity</th><th>Started</th><th>Elapsed</th><th>Worker</th></tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td><Link to={`/tasks/${task.id}`}>{task.title}</Link></td>
                <td><span className={`badge ${task.state || task.status}`}>{phaseLabel(task)}</span> <TaskHeartbeat task={task} /></td>
                <td>{task.current_action || task.stage || "—"}</td>
                <td>{(task.started_at || task.created_at)?.replace("T", " ").slice(0, 19)}</td>
                <td>{Math.round(task.elapsed_seconds ?? task.duration_seconds ?? 0)}s</td>
                <td>{task.active_worker || "Jarvis agent"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
