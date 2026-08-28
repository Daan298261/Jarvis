import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api, apiForm, fetchAudio, getPrivateKey, setPrivateKey, type Task } from "../api"
import { DelegationPanel } from "./Delegation"

type VoiceStatus = {
  stt_ready?: boolean
  tts_ready?: boolean
  detail?: string
}

export function ChatPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState("")
  const [task, setTask] = useState<Task | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [keyInput, setKeyInput] = useState<string>(getPrivateKey())
  const [showAuthModal, setShowAuthModal] = useState<boolean>(false)
  const [voice, setVoice] = useState<VoiceStatus | null>(null)
  const [recording, setRecording] = useState(false)
  const [speakResults, setSpeakResults] = useState(false)
  const [helpersOpen, setHelpersOpen] = useState(true)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const spokenRef = useRef<string>("")
  const threadRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    api<VoiceStatus>("/api/voice/status").then(setVoice).catch(() => undefined)
  }, [])

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
    if (!task) return
    const startedMs = task.started_at ? Date.parse(task.started_at) : Date.now()
    const tick = () => {
      if (["running", "queued", "waiting"].includes(task.status) && !Number.isNaN(startedMs)) {
        setElapsed(Math.max(0, Math.round((Date.now() - startedMs) / 1000)))
      } else {
        setElapsed(Math.round(task.duration_seconds || 0))
      }
    }
    tick()
    if (!["running", "queued", "waiting"].includes(task.status)) return
    const timer = window.setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [task?.status, task?.id, task?.started_at, task?.duration_seconds])

  useEffect(() => {
    if (!speakResults || !task || task.status !== "completed" || !task.result) return
    const key = `${task.id}:${task.result}`
    if (spokenRef.current === key) return
    spokenRef.current = key
    fetchAudio("/api/voice/speak", { method: "POST", body: JSON.stringify({ text: task.result.slice(0, 800) }) })
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audio.onended = () => URL.revokeObjectURL(url)
        return audio.play()
      })
      .catch(() => undefined)
  }, [speakResults, task?.id, task?.status, task?.result])

  const events = task?.events || []
  const visible = useMemo(
    () => events.filter((e) => !["model"].includes(e.kind) || e.title !== "Model is thinking"),
    [events],
  )

  useEffect(() => {
    const node = threadRef.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [visible.length, task?.result, task?.status, task?.id])

  async function submit() {
    const text = prompt.trim()
    if (!id && !text) return
    setBusy(true)
    try {
      if (id) {
        await api(`/api/tasks/${id}/continue`, { method: "POST", body: JSON.stringify({ prompt: text || "Continue this." }) })
        setPrompt("")
        const data = await api<Task>(`/api/tasks/${id}`)
        setTask(data)
      } else {
        const created = await api<Task>("/api/tasks", { method: "POST", body: JSON.stringify({ prompt: text }) })
        setPrompt("")
        navigate(`/tasks/${created.id}`)
      }
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

  async function toggleRecord() {
    if (recording) {
      recorderRef.current?.stop()
      return
    }
    if (!voice?.stt_ready) {
      alert(voice?.detail || "Local Whisper is not installed. Voice stays on this machine; cloud speech APIs are not used.")
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data)
      }
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop())
        setRecording(false)
        setBusy(true)
        try {
          const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" })
          const body = new FormData()
          body.append("audio", blob, "command.webm")
          const created = await apiForm<Task & { transcript?: string; task_id?: string }>("/api/voice/listen", body)
          const taskId = created.id || created.task_id
          if (created.transcript) setPrompt(created.transcript)
          if (taskId) navigate(`/tasks/${taskId}`)
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
      recorder.start()
      recorderRef.current = recorder
      setRecording(true)
    } catch (err: any) {
      alert(err?.message || "Microphone permission was denied.")
    }
  }

  function handleSaveKey() {
    setPrivateKey(keyInput)
    setShowAuthModal(false)
    if (id) {
      api<Task>(`/api/tasks/${id}`).then(setTask).catch(() => undefined)
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      if (!busy) void submit()
    }
  }

  const shown = id && task?.id === id ? task : null
  const running = !!shown && ["running", "queued", "waiting"].includes(shown.status)
  const empty = !id

  return (
    <div className={`chat-page${empty ? " chat-empty" : ""}`}>
      <header className="chat-head">
        {shown ? (
          <>
            <div className="chat-head-title">
              <h1>{shown.title || "Task"}</h1>
              <span className={`badge ${shown.status}`}>{shown.status}</span>
            </div>
            <p className="chat-head-meta">
              {shown.current_action || shown.stage || "Working"}
              {shown.current_tool ? ` · ${shown.current_tool}` : ""}
              {" · "}
              <span className="stat">{elapsed || Math.round(shown.duration_seconds || 0)}s</span>
              {" · "}
              <button
                type="button"
                className="rail-icon-btn"
                onClick={() => setHelpersOpen((open) => !open)}
              >
                {helpersOpen ? "Hide helpers" : "Show helpers"}
              </button>
            </p>
          </>
        ) : empty ? (
          <>
            <h1>What should Jarvis do?</h1>
            <p className="lede">Describe the end state. Jarvis plans, uses tools on this PC, and checks the result.</p>
          </>
        ) : (
          <h1>Opening task…</h1>
        )}
      </header>

      {shown && helpersOpen && (
        <div className="chat-helpers">
          <DelegationPanel key={shown.id} parentTaskId={shown.id} task={shown} compact />
        </div>
      )}

      {showAuthModal && (
        <div className="card auth-card">
          <h2>Private key needed</h2>
          <p className="lede">This Jarvis asks for a key before running work. You can also save it under Settings.</p>
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <input
              type="password"
              placeholder="jarvis_pk_..."
              value={keyInput}
              style={{ fontFamily: "monospace", flex: 1 }}
              onChange={(e) => setKeyInput(e.target.value)}
            />
            <button className="btn" onClick={handleSaveKey}>Save</button>
          </div>
        </div>
      )}

      <div className="chat-thread" ref={threadRef}>
        {shown && (
          <>
            {shown.prompt && (
              <div className="bubble bubble-user">
                <strong>You</strong>
                <p>{shown.prompt}</p>
              </div>
            )}
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
              {!visible.length && running && <p className="lede">Waiting for the first action.</p>}
            </div>
            {(shown.result || shown.error || shown.status === "completed") && (
              <div className="bubble bubble-result">
                <strong>Result</strong>
                <div className="report">{shown.result || shown.error || "The final report appears after verification."}</div>
                {shown.waiting_for_confirmation && (
                  <div className="row" style={{ marginTop: 12 }}>
                    <button className="btn" onClick={() => api(`/api/tasks/${shown.id}/continue`, { method: "POST", body: JSON.stringify({ approve: true }) })}>Approve</button>
                    <button className="btn secondary" onClick={() => api(`/api/tasks/${shown.id}/continue`, { method: "POST", body: JSON.stringify({ approve: false }) })}>Reject</button>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <div className="composer-dock">
        <textarea
          className="command"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onComposerKeyDown}
          placeholder={id ? "Add a follow-up, or press Send to continue…" : "Organize these files, fix this project, research a topic…"}
        />
        <div className="row composer-actions">
          <button className="btn" disabled={busy || (!id && !prompt.trim())} onClick={submit}>
            {id ? (prompt.trim() ? "Send" : "Continue") : "Send"}
          </button>
          <button
            className={recording ? "btn recording" : "btn secondary"}
            disabled={busy}
            onClick={toggleRecord}
            title={voice?.stt_ready ? "Record a spoken command (local Whisper)" : (voice?.detail || "Local Whisper is not installed")}
          >
            {recording ? "Stop recording" : "Speak"}
          </button>
          <label className="row composer-check">
            <input type="checkbox" checked={speakResults} onChange={(e) => setSpeakResults(e.target.checked)} />
            Speak results
          </label>
          {shown && running && (
            <button className="btn secondary" onClick={() => api(`/api/tasks/${shown.id}/cancel`, { method: "POST" })}>
              Cancel
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
