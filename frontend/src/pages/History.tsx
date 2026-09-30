import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api, type Task } from "../api"
import { TaskStatusMeta, TaskVerificationBadge } from "../components/TaskStatusMeta"
import { formatElapsedSeconds } from "../taskStatus"

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
            <tr>
              <th>Title</th>
              <th>Phase / activity</th>
              <th>Verification</th>
              <th>Started</th>
              <th>Elapsed</th>
              <th>Worker</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td><Link to={`/tasks/${task.id}`}>{task.title}</Link></td>
                <td><TaskStatusMeta task={task} showElapsed={false} /></td>
                <td><TaskVerificationBadge task={task} /></td>
                <td>{(task.started_at || task.created_at)?.replace("T", " ").slice(0, 19)}</td>
                <td>{formatElapsedSeconds(task.elapsed_seconds ?? task.duration_seconds) || "—"}</td>
                <td>{task.active_worker || "Jarvis agent"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
