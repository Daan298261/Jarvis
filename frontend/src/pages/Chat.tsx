import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api, getPrivateKey, setPrivateKey, type Task } from "../api"

export function ChatPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState("")
  const [task, setTask] = useState<Task | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [keyInput, setKeyInput] = useState<string>(getPrivateKey())
  const [showAuthModal, setShowAuthModal] = useState<boolean>(false)

  useEffect(() => {
    if (!id) return
    let timer: number
    const load = async () => {
      try {
        const data = await api<Task>(`/api/tasks/${id}`)
        setTask(data)
      } catch (err: any) {
        if (err.message && err.message.toLowerCase().includes("authentication required")) {
          setShowAuthModal(true)
        }
      }
    }
    load()
    timer = window.setInterval(() => load().catch(() => undefined), 2000)
    return () => clearInterval(timer)
  }, [id])

  useEffect(() => {
    if (!task || !["running", "queued", "waiting"].includes(task.status)) {
      setElapsed(Math.round(task?.duration_seconds || 0))
      return
    }
    const origin = task.started_at ? Date.parse(task.started_at) : Date.now()
    const tick = () => setElapsed(Math.max(0, Math.round((Date.now() - origin) / 1000)))
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [task?.status, task?.id, task?.started_at])

  async function submit() {
    if (!prompt.trim()) return
    setBusy(true)
    try {
      const created = await api<Task>("/api/tasks", { method: "POST", body: JSON.stringify({ prompt }) })
      setPrompt("")
      navigate(`/tasks/${created.id}`)
    } catch (err: any) {
      if (err.message && err.message.toLowerCase().includes("authentication required")) {
        setShowAuthModal(true)
      } else {
        alert(err.message)
      }
    } finally {
      setBusy(false)
    }
  }

  function handleSaveKey() {
    setPrivateKey(keyInput)
    setShowAuthModal(false)
    if (id) {
      api<Task>(`/api/tasks/${id}`).then(setTask).catch(() => undefined)
    }
  }

  const events = task?.events || []
  const visible = useMemo(
    () => events.filter((e) => !["model"].includes(e.kind) || e.title !== "Model is thinking"),
    [events],
  )

  return (
    <div>
      <h1>Command</h1>
      <p className="lede">Give Jarvis an end state. It will plan, use tools, recover from errors, and verify the result.</p>

      {showAuthModal && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--bad)", padding: "16px" }}>
          <h3>Private Key Authentication Required</h3>
          <p className="lede">This Jarvis instance requires a private key for all queries.</p>
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <input
              type="password"
              placeholder="Enter Private Key (jarvis_pk_...)"
              value={keyInput}
              style={{ fontFamily: "monospace", flex: 1 }}
              onChange={(e) => setKeyInput(e.target.value)}
            />
            <button className="btn" onClick={handleSaveKey}>Save Key</button>
          </div>
        </div>
      )}

      <div className="grid two">
        <div className="card">
          <textarea
            className="command"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Organize these files, fix this project, research a topic, control the browser..."
          />
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={busy} onClick={submit}>Run task</button>
            {task && (task.status === "running" || task.status === "waiting") && (
              <button className="btn secondary" onClick={() => api(`/api/tasks/${task.id}/cancel`, { method: "POST" })}>Cancel</button>
            )}
            {task && task.status !== "running" && (
              <button
                className="btn secondary"
                onClick={() => api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ prompt: "Continue this." }) })}
              >
                Continue this
              </button>
            )}
          </div>
        </div>
        <div className="card">
          <h2>Live status</h2>
          {task ? (
            <div className="kv">
              <b>Task</b><span>{task.title}</span>
              <b>Status</b><span className={`badge ${task.status}`}>{task.status}</span>
              <b>Mode</b><span>{task.execution_mode || "balanced"}</span>
              <b>Class</b><span>{task.task_class || "—"}</span>
              <b>Stage</b><span>{task.stage}</span>
              <b>Action</b><span>{task.current_action || "—"}</span>
              <b>Tool</b><span>{task.current_tool || "—"}</span>
              <b>Elapsed</b><span className="stat">{elapsed || Math.round(task.duration_seconds || 0)}s</span>
              <b>Retries</b><span>{task.retries}</span>
              <b>Verified</b><span>{task.verification ? "yes" : "pending"}</span>
            </div>
          ) : (
            <p className="lede">No active task.</p>
          )}
        </div>
      </div>
      {task && (
        <div className="grid two" style={{ marginTop: 16 }}>
          <div className="card">
            <h2>Activity</h2>
            <div className="timeline">
              {visible.map((event, index) => (
                <div className="t-item" key={index}>
                  <div className="rail" />
                  <div>
                    <strong>{event.title}</strong>
                    {event.detail && <p>{event.detail.slice(0, 800)}</p>}
                  </div>
                </div>
              ))}
              {!visible.length && <p className="lede">Waiting for the first action.</p>}
            </div>
          </div>
          <div className="card">
            <h2>Result</h2>
            <div className="report">{task.result || task.error || "The final report appears after verification."}</div>
            {task.waiting_for_confirmation && (
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" onClick={() => api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ approve: true }) })}>Approve</button>
                <button className="btn secondary" onClick={() => api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ approve: false }) })}>Reject</button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
