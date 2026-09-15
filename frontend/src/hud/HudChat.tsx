import { useEffect, useRef, useState, type KeyboardEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api, getPrivateKey, setPrivateKey, type Task } from "../api"
import { OwnerChatTranscript } from "../chat/OwnerChatTranscript"
import { prunePendingUserTexts } from "../chat/ownerChatView"
import { ChatTtsMuteButton } from "../tts/ChatTtsMuteButton"
import { stopChatTts } from "../tts/chatTtsPlayer"
import { useSpeakChatReplies } from "../tts/chatTtsSettings"
import { useTaskSpeech } from "../tts/useTaskSpeech"
import { useVoiceProfileSwitching } from "../tts/voiceProfiles"
import { useHexStrikeSuiteActive } from "./hexstrikeSuite"

type HudChatProps = {
  onMoodChange?: (opts: { recording: boolean; speaking: boolean; task: Task | null }) => void
}

export function HudChat({ onMoodChange }: HudChatProps) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState("")
  const [task, setTask] = useState<Task | null>(null)
  const [pending, setPending] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [keyInput, setKeyInput] = useState<string>(getPrivateKey())
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [recording] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [speakChatReplies, setSpeakChatReplies] = useSpeakChatReplies()
  const threadRef = useRef<HTMLDivElement | null>(null)
  const { active: hexStrikeActive } = useHexStrikeSuiteActive()
  const voiceSwitching = useVoiceProfileSwitching()
  const composerLocked = busy || voiceSwitching

  useTaskSpeech(id && task?.id === id ? task : null, speakChatReplies, setSpeaking)

  useEffect(() => {
    if (!id) {
      setTask(null)
      setPending([])
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
    onMoodChange?.({ recording, speaking, task: id && task?.id === id ? task : null })
  }, [recording, speaking, task, id, onMoodChange])

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

  async function submit() {
    const text = prompt.trim()
    if (!id && !text) return
    if (voiceSwitching) return
    stopChatTts()
    setSpeaking(false)
    setBusy(true)
    try {
      if (id) {
        if (text) setPending((current) => (current.includes(text) ? current : [...current, text]))
        await api(`/api/tasks/${id}/continue`, {
          method: "POST",
          body: JSON.stringify({ prompt: text || "Continue this." }),
        })
        setPrompt("")
        const data = await api<Task>(`/api/tasks/${id}`)
        setTask(data)
      } else {
        const body: { prompt: string; security_role?: string } = { prompt: text }
        if (hexStrikeActive) body.security_role = "blue-team"
        const created = await api<Task>("/api/tasks", { method: "POST", body: JSON.stringify(body) })
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
      if (!composerLocked) void submit()
    }
  }

  const shown = id && task?.id === id ? task : null
  const running = !!shown && ["running", "queued", "waiting"].includes(shown.status)
  const showThread = !!id

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

      {showThread && (
        <div className="hud-thread" ref={threadRef} aria-live="polite">
          {!shown && <p className="hud-thread-empty">Loading task…</p>}
          {shown && (
            <OwnerChatTranscript
              key={shown.id}
              variant="hud"
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
      )}

      <div className={`hud-composer${voiceSwitching ? " voice-switching" : ""}`}>
        <textarea
          className="hud-command"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onComposerKeyDown}
          placeholder={voiceSwitching ? "Switching voice…" : id ? "Message…" : "Ask Jarvis anything…"}
          rows={2}
          aria-label="Message Jarvis"
          aria-disabled={voiceSwitching}
        />
        <div className="hud-composer-actions">
          {voiceSwitching && (
            <span className="hud-composer-voice-status" role="status">
              Switching voice…
            </span>
          )}
          <ChatTtsMuteButton
            enabled={speakChatReplies}
            variant="hud"
            onToggle={(enabled) => { void setSpeakChatReplies(enabled) }}
          />
          {shown && running && (
            <button
              className="btn secondary"
              type="button"
              onClick={() => api(`/api/tasks/${shown.id}/cancel`, { method: "POST" })}
            >
              Cancel
            </button>
          )}
          <button className="btn hud-send" type="button" disabled={composerLocked || (!id && !prompt.trim())} onClick={submit}>
            {id ? (prompt.trim() ? "Send" : "Continue") : "Send"}
          </button>
        </div>
      </div>
    </div>
  )
}
