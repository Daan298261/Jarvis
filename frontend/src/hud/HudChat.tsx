import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api, getPrivateKey, setPrivateKey, type Task } from "../api"

type HudChatProps = {
  onMoodChange?: (opts: { recording: boolean; speaking: boolean; task: Task | null }) => void
}

export function HudChat({ onMoodChange }: HudChatProps) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState("")
  const [task, setTask] = useState<Task | null>(null)
  const [busy, setBusy] = useState(false)
  const [keyInput, setKeyInput] = useState<string>(getPrivateKey())
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [recording] = useState(false)
  const threadRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!id) {
      setTask(null)
      return
    }
    let timer: number
    const load = async () => {
      try {
        const data = await api<Task>(`/api/tasks/${id}`)
        setTask(data)
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err)
        if (message.toLowerCase().includes("authentication required")) {
          setShowAuthModal(true)
        }
      }
    }
    load()
    timer = window.setInterval(() => load().catch(() => undefined), 2000)
    return () => clearInterval(timer)
  }, [id])

  useEffect(() => {
    onMoodChange?.({ recording, speaking: false, task: id && task?.id === id ? task : null })
  }, [recording, task, id, onMoodChange])

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
        await api(`/api/tasks/${id}/continue`, {
          method: "POST",
          body: JSON.stringify({ prompt: text || "Continue this." }),
        })
        setPrompt("")
        const data = await api<Task>(`/api/tasks/${id}`)
        setTask(data)
      } else {
        const created = await api<Task>("/api/tasks", { method: "POST", body: JSON.stringify({ prompt: text }) })
        setPrompt("")
        navigate(`/tasks/${created.id}`)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err)
      if (message.toLowerCase().includes("authentication required")) {
        setShowAuthModal(true)
      } else {
        alert(message)
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
    <div className="hud-chat">
      {showAuthModal && (
        <div className="hud-auth-card">
          <strong>Private key needed</strong>
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <input
              type="password"
              placeholder="jarvis_pk_..."
              value={keyInput}
              style={{ fontFamily: "monospace", flex: 1 }}
              onChange={(e) => setKeyInput(e.target.value)}
            />
            <button className="btn hud-admin-btn" type="button" onClick={handleSaveKey}>Save</button>
          </div>
        </div>
      )}

      <div className="hud-thread" ref={threadRef}>
        {empty && !shown && (
          <p className="hud-thread-empty">What should Jarvis do on this PC?</p>
        )}
        {shown && (
          <>
            {shown.prompt && (
              <div className="hud-bubble hud-bubble-user">
                <span className="hud-bubble-label">You</span>
                <p>{shown.prompt}</p>
              </div>
            )}
            {visible.slice(-6).map((event, index) => (
              <div className="hud-bubble hud-bubble-event" key={`${event.created_at}-${index}`}>
                <span className="hud-bubble-label">{event.title}</span>
                {event.detail && <p>{event.detail.slice(0, 400)}</p>}
              </div>
            ))}
            {!visible.length && running && <p className="hud-thread-empty">Working…</p>}
            {(shown.result || shown.error) && (
              <div className="hud-bubble hud-bubble-result">
                <span className="hud-bubble-label">Result</span>
                <div className="report">{shown.result || shown.error}</div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="hud-composer">
        <textarea
          className="hud-command"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onComposerKeyDown}
          placeholder={id ? "Follow up or press Send to continue…" : "Describe the end state…"}
          rows={2}
        />
        <div className="hud-composer-actions">
          <button className="btn hud-send" type="button" disabled={busy || (!id && !prompt.trim())} onClick={submit}>
            {id ? (prompt.trim() ? "Send" : "Continue") : "Send"}
          </button>
          <button className="btn hud-mic-stub secondary" type="button" disabled title="Mic slot (stub)">
            Mic
          </button>
          {shown && running && (
            <button
              className="btn secondary"
              type="button"
              onClick={() => api(`/api/tasks/${shown.id}/cancel`, { method: "POST" })}
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
