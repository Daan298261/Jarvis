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
import { useVoiceProfileSwitching } from "../tts/voiceProfiles"
import { usePendingApprovals } from "../chat/pendingApprovals"
import { useHexStrikeSuiteActive } from "./hexstrikeSuite"
import { SETUP_PROBLEM_WORKING, isAuthFailureMessage } from "../setup/ownerFacing"
import { MediaComposerBar } from "../components/MediaComposerBar"
import { useMediaUploads } from "../chat/useMediaUploads"

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
  const [showSetupProblem, setShowSetupProblem] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [speakChatReplies, setSpeakChatReplies] = useSpeakChatReplies()
  const threadRef = useRef<HTMLDivElement | null>(null)
  const { active: hexStrikeActive } = useHexStrikeSuiteActive()
  const { ingestPayload } = usePendingApprovals()
  const voiceSwitching = useVoiceProfileSwitching()
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
  const composerLocked = busy || voiceSwitching || media.hasUploading

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
        if (isAuthFailureMessage(message)) {
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

  useEffect(() => {
    if (!task?.waiting_for_confirmation || !task.confirmation_payload) return
    ingestPayload(task.confirmation_payload)
  }, [task?.waiting_for_confirmation, task?.confirmation_payload, ingestPayload])

  async function submit() {
    const text = prompt.trim()
    const mediaIds = media.readyIds
    if (!id && !text && !mediaIds.length) return
    if (voiceSwitching) return
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
        const body: { prompt: string; security_role?: string; media_ids?: string[] } = {
          prompt: text || (mediaIds.length ? "Review the attached media." : ""),
          media_ids: mediaIds,
        }
        if (hexStrikeActive) body.security_role = "blue-team"
        const created = await api<Task>("/api/tasks", { method: "POST", body: JSON.stringify(body) })
        setPrompt("")
        media.clear()
        navigate(`/tasks/${created.id}`)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err)
      if (isAuthFailureMessage(message)) {
        setShowSetupProblem(true)
        const recovered = await ensureDesktopSession()
        if (recovered) setShowSetupProblem(false)
      } else {
        alert(message)
      }
    } finally {
      setBusy(false)
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
      {showSetupProblem && (
        <div className="hud-auth-card" role="status">
          <strong>Setup problem</strong>
          <p className="lede" style={{ marginTop: 8 }}>{SETUP_PROBLEM_WORKING}</p>
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
              createdAt={shown.created_at}
              updatedAt={shown.updated_at}
            />
          )}
        </div>
      )}

      <div className={`hud-composer${voiceSwitching ? " voice-switching" : ""}`}>
        <VoiceWaveformBar speaking={speaking} listening={listening} />
        <MediaComposerBar
          className="media-composer-bar hud-media-bar"
          items={media.items}
          onPick={media.uploadFiles}
          onRemove={media.remove}
          disabled={composerLocked}
        />
        <textarea
          className="hud-command"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onComposerKeyDown}
          placeholder={voiceSwitching ? "Switching voice…" : id ? "Message…" : "Ask ANZU anything…"}
          rows={2}
          aria-label="Message ANZU"
          aria-disabled={voiceSwitching}
        />
        <div className="hud-composer-actions">
          {voiceSwitching && (
            <span className="hud-composer-voice-status" role="status">
              Switching voice…
            </span>
          )}
          <button
            className={recording ? "btn recording" : "btn secondary"}
            type="button"
            disabled={!recording && composerLocked}
            onClick={() => void toggleRecord()}
            title={voice?.stt_ready ? "Record a spoken command (local Whisper)" : (voice?.detail || "Local Whisper is not installed")}
          >
            {recording ? "Stop" : "Speak"}
          </button>
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
          <button
            className="btn hud-send"
            type="button"
            disabled={composerLocked || (!id && !prompt.trim() && !media.readyIds.length)}
            onClick={submit}
          >
            {id ? (prompt.trim() ? "Send" : "Continue") : "Send"}
          </button>
        </div>
      </div>
    </div>
  )
}
