import { useEffect, useRef, useState, type KeyboardEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api, ensureDesktopSession, type Task } from "../api"
import { OwnerChatTranscript } from "../chat/OwnerChatTranscript"
import { prunePendingUserTexts } from "../chat/ownerChatView"
import { VoiceWaveformBar } from "../chat/VoiceWaveformBar"
import { useLocalVoiceListen } from "../chat/useLocalVoiceListen"
import { ChatTtsMuteButton } from "../tts/ChatTtsMuteButton"
import { stopChatTts } from "../tts/chatTtsPlayer"
import { useSpeakChatReplies } from "../tts/chatTtsSettings"
import { useTaskSpeech } from "../tts/useTaskSpeech"
import { AdvancedDisclosure } from "../components/AdvancedDisclosure"
import { TaskActivityPanel } from "../components/TaskActivity"
import { MediaComposerBar } from "../components/MediaComposerBar"
import { useMediaUploads } from "../chat/useMediaUploads"
import { DelegationPanel } from "./Delegation"
import { usePendingApprovals } from "../chat/pendingApprovals"
import { SETUP_PROBLEM_WORKING, isAuthFailureMessage } from "../setup/ownerFacing"

export function ChatPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState("")
  const [task, setTask] = useState<Task | null>(null)
  const [pending, setPending] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [showSetupProblem, setShowSetupProblem] = useState<boolean>(false)
  const [speaking, setSpeaking] = useState(false)
  const [speakChatReplies, setSpeakChatReplies] = useSpeakChatReplies()
  const threadRef = useRef<HTMLDivElement | null>(null)
  const { ingestPayload } = usePendingApprovals()
  const media = useMediaUploads()
  const { recording, listening, voice, toggleRecord } = useLocalVoiceListen({
    setBusy,
    onResult: ({ transcript, taskId }) => {
      if (transcript) setPrompt(transcript)
      if (taskId) navigate(`/tasks/${taskId}`)
    },
    onAuthFailure: async () => {
      setShowSetupProblem(true)
      const recovered = await ensureDesktopSession()
      if (recovered) setShowSetupProblem(false)
      return recovered
    },
    onError: (message) => alert(message),
  })

  useTaskSpeech(id && task?.id === id ? task : null, speakChatReplies, setSpeaking)

  useEffect(() => {
    if (!id) {
      setPending([])
      return
    }
    let timer: number
    const load = async () => {
      try {
        const data = await api<Task>(`/api/tasks/${id}`)
        setTask(data)
      } catch (err: any) {
        if (err.message && isAuthFailureMessage(err.message)) {
          setShowSetupProblem(true)
          const recovered = await ensureDesktopSession()
          if (recovered) {
            setShowSetupProblem(false)
            api<Task>(`/api/tasks/${id}`).then(setTask).catch(() => undefined)
          }
        }
      }
    }
    load()
    timer = window.setInterval(() => load().catch(() => undefined), 400)
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
    const node = threadRef.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [task?.events?.length, task?.result, task?.status, task?.id, task?.messages?.length, pending.length])

  useEffect(() => {
    if (!task) return
    setPending((current) =>
      prunePendingUserTexts(current, {
        prompt: task.prompt,
        result: task.result,
        error: task.error,
        messages: task.messages,
      }),
    )
  }, [task?.messages, task?.prompt, task?.result, task?.error])

  useEffect(() => {
    if (!task?.waiting_for_confirmation || !task.confirmation_payload) return
    ingestPayload(task.confirmation_payload)
  }, [task?.waiting_for_confirmation, task?.confirmation_payload, ingestPayload])

  async function submit() {
    const text = prompt.trim()
    const mediaIds = media.readyIds
    if (!id && !text && !mediaIds.length) return
    if (media.hasUploading) return
    stopChatTts()
    setSpeaking(false)
    setBusy(true)
    try {
      if (id) {
        if (text) setPending((current) => (current.includes(text) ? current : [...current, text]))
        await api(`/api/tasks/${id}/continue`, {
          method: "POST",
          body: JSON.stringify({
            prompt: text || (mediaIds.length ? "Review the attached media." : "Continue this."),
            media_ids: mediaIds,
          }),
        })
        setPrompt("")
        media.clear()
        const data = await api<Task>(`/api/tasks/${id}`)
        setTask(data)
      } else {
        const created = await api<Task>("/api/tasks", {
          method: "POST",
          body: JSON.stringify({
            prompt: text || (mediaIds.length ? "Review the attached media." : ""),
            media_ids: mediaIds,
          }),
        })
        setPrompt("")
        media.clear()
        navigate(`/tasks/${created.id}`)
      }
    } catch (err: any) {
      if (err.message && isAuthFailureMessage(err.message)) {
        setShowSetupProblem(true)
        const recovered = await ensureDesktopSession()
        if (recovered) {
          setShowSetupProblem(false)
        }
      } else {
        alert(err.message)
      }
    } finally {
      setBusy(false)
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
              <span className={`badge ${shown.state || shown.status}`}>{shown.state || shown.status}</span>
            </div>
            <p className="chat-head-meta">
              {shown.current_action || shown.stage || "Working"}
              {shown.current_tool ? ` · ${shown.current_tool}` : ""}
              {" · "}
              <span className="stat">{elapsed || Math.round(shown.duration_seconds || 0)}s</span>
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

      {shown && (
        <AdvancedDisclosure>
          <div className="chat-activity-wrap">
            <TaskActivityPanel task={shown} elapsed={elapsed || Math.round(shown.elapsed_seconds || shown.duration_seconds || 0)} />
          </div>
          <div className="chat-helpers">
            <DelegationPanel key={shown.id} parentTaskId={shown.id} task={shown} compact />
          </div>
        </AdvancedDisclosure>
      )}

      {showSetupProblem && (
        <div className="card auth-card" role="status">
          <h2>Setup problem</h2>
          <p className="lede">{SETUP_PROBLEM_WORKING}</p>
        </div>
      )}

      <div className="chat-thread" ref={threadRef}>
        {shown && (
          <OwnerChatTranscript
            key={shown.id}
            variant="classic"
            taskId={shown.id}
            prompt={shown.prompt}
            status={shown.status}
            stage={shown.stage}
            current_action={shown.current_action}
            current_tool={shown.current_tool}
            waiting_for_confirmation={shown.waiting_for_confirmation}
            confirmation_payload={shown.confirmation_payload}
            result={shown.result}
            error={shown.error}
            events={shown.events}
            messages={shown.messages}
            pending={pending}
          />
        )}
      </div>

      <div className="composer-dock">
        <VoiceWaveformBar speaking={speaking} listening={listening} />
        <MediaComposerBar
          items={media.items}
          onPick={media.uploadFiles}
          onRemove={media.remove}
          disabled={busy}
        />
        <textarea
          className="command"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onComposerKeyDown}
          placeholder={id ? "Message…" : "Organize these files, fix this project, research a topic…"}
        />
        <div className="row composer-actions">
          <button
            className="btn"
            disabled={busy || media.hasUploading || (!id && !prompt.trim() && !media.readyIds.length)}
            onClick={submit}
          >
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
          <ChatTtsMuteButton
            enabled={speakChatReplies}
            onToggle={(enabled) => { void setSpeakChatReplies(enabled) }}
          />
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
