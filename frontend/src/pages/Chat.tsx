import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api, apiUpload, apiWav, type Task, type TimelineStep } from "../api"
import { playWav, recordWav } from "../voice"

function isHiddenThought(event: TimelineStep): boolean {
  const title = (event.title || "").trim().toLowerCase()
  if (title === "model is thinking" || title === "reasoning complete") return true
  return event.kind === "model" && title.includes("thinking")
}

export function ChatPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState("")
  const [task, setTask] = useState<Task | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [executionMode, setExecutionMode] = useState("balanced")
  const [autonomy, setAutonomy] = useState("trusted")
  const [recording, setRecording] = useState(false)
  const [voiceBusy, setVoiceBusy] = useState("")
  const [voiceError, setVoiceError] = useState("")
  const [speakResults, setSpeakResults] = useState(false)
  const [stopper, setStopper] = useState<null | (() => Promise<Blob>)>(null)
  const spokenId = useRef("")

  useEffect(() => {
    api<{ execution_mode?: string; autonomy?: string; voice?: { speak_results?: boolean } }>("/api/settings")
      .then((settings) => {
        if (settings.execution_mode) setExecutionMode(settings.execution_mode)
        if (settings.autonomy) setAutonomy(settings.autonomy)
        setSpeakResults(Boolean(settings.voice?.speak_results))
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!id) return
    let timer: number
    const load = async () => {
      const data = await api<Task>(`/api/tasks/${id}`)
      setTask(data)
    }
    load().catch(console.error)
    timer = window.setInterval(() => load().catch(() => undefined), 2000)
    return () => clearInterval(timer)
  }, [id])

  useEffect(() => {
    if (!task || !["running", "queued", "waiting"].includes(task.status)) return
    const started = Date.now()
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000) + Math.round(task.duration_seconds || 0)), 1000)
    return () => clearInterval(timer)
  }, [task?.status, task?.id])

  useEffect(() => {
    if (!task?.result || task.status !== "completed" || !speakResults) return
    if (spokenId.current === task.id) return
    spokenId.current = task.id
    playWavResult(task.result).catch(() => undefined)
  }, [task?.id, task?.status, task?.result, speakResults])

  async function playWavResult(text: string) {
    await playWav(await apiWav("/api/voice/speak", text))
  }

  async function submit() {
    if (!prompt.trim()) return
    setBusy(true)
    try {
      const created = await api<Task>("/api/tasks", { method: "POST", body: JSON.stringify({ prompt, execution_mode: executionMode, autonomy }) })
      setPrompt("")
      navigate(`/tasks/${created.id}`)
    } finally {
      setBusy(false)
    }
  }

  async function toggleMic() {
    setVoiceError("")
    if (recording && stopper) {
      setVoiceBusy("transcribe")
      try {
        const blob = await stopper()
        setStopper(null)
        setRecording(false)
        const body = new FormData()
        body.append("audio", blob, "speech.wav")
        const result = await apiUpload<{ text: string }>("/api/voice/transcribe", body)
        if (result.text) setPrompt((prev) => (prev ? `${prev.trim()} ${result.text}` : result.text))
        else setVoiceError("Whisper heard no speech")
      } catch (err) {
        setVoiceError(err instanceof Error ? err.message : "Transcription failed")
      } finally {
        setVoiceBusy("")
      }
      return
    }
    try {
      const session = await recordWav()
      setStopper(() => session.stop)
      setRecording(true)
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : "Microphone permission denied")
    }
  }

  async function speakResult() {
    const spoken = (task?.result || prompt).trim()
    if (!spoken) return
    setVoiceBusy("speak")
    setVoiceError("")
    try {
      await playWavResult(spoken)
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : "TTS failed")
    } finally {
      setVoiceBusy("")
    }
  }

  const events: TimelineStep[] = task?.timeline?.length ? task.timeline : (task?.events || [])
  const visible = useMemo(
    () => events.filter((e) => !isHiddenThought(e)),
    [events],
  )
  const confirmReason = useMemo(() => {
    if (!task?.confirmation_payload) return ""
    try {
      const data = JSON.parse(task.confirmation_payload)
      return typeof data.reason === "string" ? data.reason : ""
    } catch {
      return ""
    }
  }, [task?.confirmation_payload])

  return (
    <div>
      <h1>Command</h1>
      <p className="lede">Give Jarvis an end state. It will plan, use tools, recover from errors, and verify the result.</p>
      <div className="grid two">
        <div className="card">
          <textarea className="command" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Organize these files, fix this project, research a topic, control the browser..." />
          <div className="row" style={{ marginTop: 12, flexWrap: "wrap", gap: 8 }}>
            <label className="mode-pick">Autonomy
              <select value={autonomy} onChange={(e) => setAutonomy(e.target.value)}>
                <option value="interactive">Interactive</option>
                <option value="trusted">Trusted</option>
                <option value="autonomous">Autonomous</option>
              </select>
            </label>
            <label className="mode-pick">Execution
              <select value={executionMode} onChange={(e) => setExecutionMode(e.target.value)}>
                <option value="fast">Fast</option>
                <option value="balanced">Balanced</option>
                <option value="reliable">Reliable</option>
              </select>
            </label>
            <button className="btn" disabled={busy} onClick={submit}>Run task</button>
            <button className="btn secondary" disabled={busy || !!voiceBusy} onClick={toggleMic}>
              {recording ? "Stop mic" : voiceBusy === "transcribe" ? "Transcribing…" : "Mic"}
            </button>
            <button className="btn secondary" disabled={!!voiceBusy || !(task?.result || prompt).trim()} onClick={speakResult}>
              {voiceBusy === "speak" ? "Speaking…" : "Speak"}
            </button>
            {task && (task.status === "running" || task.status === "waiting") && (
              <button className="btn secondary" onClick={() => api(`/api/tasks/${task.id}/cancel`, { method: "POST" })}>Cancel</button>
            )}
            {task && task.status !== "running" && task.status !== "queued" && !task.waiting_for_confirmation && (
              <button className="btn secondary" onClick={() => api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ prompt: "Continue this." }) })}>Continue this</button>
            )}
          </div>
          {voiceError ? <p className="lede" style={{ color: "var(--bad)", marginBottom: 0 }}>{voiceError}</p> : null}
        </div>
        <div className="card">
          <h2>Live status</h2>
          {task ? (
            <div className="kv">
              <b>Task</b><span>{task.title}</span>
              <b>Status</b><span className={`badge ${task.status}`}>{task.status}</span>
              <b>Autonomy</b><span>{task.autonomy || autonomy}</span>
              <b>Mode</b><span>{task.execution_mode || executionMode}</span>
              <b>Class</b><span>{task.task_class || "—"}</span>
              <b>Worker</b><span>{task.selected_worker || "native"}</span>
              <b>Stage</b><span>{task.stage}</span>
              <b>Action</b><span>{task.current_action || "—"}</span>
              <b>Tool</b><span>{task.current_tool || "—"}</span>
              <b>Elapsed</b><span className="stat">{elapsed || Math.round(task.duration_seconds || 0)}s</span>
              <b>Retries</b><span>{task.retries}</span>
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
                    {event.expandable ? (
                      <details className="t-details">
                        <summary>
                          {event.backend || event.tool || "tool"}
                          {event.duration_ms ? ` · ${Math.round(event.duration_ms)}ms` : ""}
                          {event.exit_code != null ? ` · exit ${event.exit_code}` : ""}
                          {event.success === false ? " · failed" : ""}
                        </summary>
                        {event.arguments ? <p><b>arguments</b>{"\n"}{event.arguments.slice(0, 1500)}</p> : null}
                        {event.stdout ? <p><b>stdout</b>{"\n"}{event.stdout.slice(0, 4000)}</p> : null}
                        {event.stderr ? <p><b>stderr</b>{"\n"}{event.stderr.slice(0, 2000)}</p> : null}
                        {!event.stdout && !event.stderr && event.detail ? <p>{event.detail.slice(0, 800)}</p> : null}
                      </details>
                    ) : (
                      event.detail ? <p>{event.detail.slice(0, 800)}</p> : null
                    )}
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
              <div style={{ marginTop: 12 }}>
                {confirmReason ? <p className="lede">{confirmReason}</p> : null}
                <div className="row">
                  <button className="btn" onClick={() => api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ approve: true }) })}>Approve</button>
                  <button className="btn secondary" onClick={() => api(`/api/tasks/${task.id}/continue`, { method: "POST", body: JSON.stringify({ approve: false }) })}>Reject</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
