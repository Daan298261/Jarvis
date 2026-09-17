import { useEffect, useMemo, useRef, useState } from "react"
import { api, apiForm } from "../api"
import { useSpeakChatReplies } from "../tts/chatTtsSettings"
import { speakChatReply, stopChatTts } from "../tts/chatTtsPlayer"
import type { ApprovalDecideBody, ApprovalDecideMode, ConfirmationPayload, PermissionCatalogItem } from "./approvalsApi"
import { inferRequiresOwnerInput } from "./approvalsApi"
import { interpretSpokenGrant, spokenGrantUnclearMessage } from "./spokenGrant"
import "./permissionPrompt.css"

export type { ConfirmationPayload, PermissionCatalogItem } from "./approvalsApi"

type PermissionSnapshot = {
  permissions: PermissionCatalogItem[]
  groups: Record<string, PermissionCatalogItem[]>
}

type PermissionPromptProps = {
  taskId?: string
  pendingId?: string
  payload?: unknown
  variant?: "hud" | "classic" | "phone" | "modal"
  onDecide?: (body: ApprovalDecideBody) => Promise<void>
  onDismiss?: () => void
}

const GROUP_LABELS: Record<string, string> = {
  computer: "Computer use",
  network: "Network",
  cyber: "Cybersecurity suite",
  blue: "Blue team (defensive)",
  red: "Red team (flags only)",
}

const LISTEN_MS = 8000
const OWNER_NOTE_MAX = 500

export function parseConfirmationPayload(raw: unknown): ConfirmationPayload | null {
  if (raw == null || raw === "") return null
  if (typeof raw === "object") return raw as ConfirmationPayload
  if (typeof raw !== "string") return null
  try {
    const parsed = JSON.parse(raw) as ConfirmationPayload
    return parsed && typeof parsed === "object" ? parsed : null
  } catch {
    return null
  }
}

export function PermissionPrompt({
  taskId,
  pendingId,
  payload,
  variant = "classic",
  onDecide,
  onDismiss,
}: PermissionPromptProps) {
  const parsed = useMemo(() => parseConfirmationPayload(payload), [payload])
  const resolvedPendingId = pendingId || parsed?.pending_id
  const usesDecideApi = Boolean(resolvedPendingId && onDecide)
  const isPermission =
    parsed?.kind === "permission" || Boolean(parsed?.permission_id) || usesDecideApi
  const requiresOwnerInput = useMemo(() => {
    if (!parsed) return false
    const record = parsed as ConfirmationPayload & Record<string, unknown>
    return inferRequiresOwnerInput(record)
  }, [parsed])

  const [moreOpen, setMoreOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [ownerNote, setOwnerNote] = useState("")
  const [catalog, setCatalog] = useState<PermissionCatalogItem[]>(parsed?.catalog || [])
  const [speakChatReplies] = useSpeakChatReplies()
  const [listening, setListening] = useState(false)
  const [sttReady, setSttReady] = useState<boolean | null>(null)
  const [voiceStatus, setVoiceStatus] = useState("")
  const recorderRef = useRef<MediaRecorder | null>(null)
  const listenTimerRef = useRef<number | null>(null)
  const settledRef = useRef(false)
  const listenGenRef = useRef(0)
  const sttReadyRef = useRef<boolean | null>(null)
  sttReadyRef.current = sttReady

  const allowBlocked = requiresOwnerInput && !ownerNote.trim()

  useEffect(() => {
    let cancelled = false
    api<{ stt_ready?: boolean; detail?: string }>("/api/voice/status")
      .then((status) => {
        if (cancelled) return
        setSttReady(Boolean(status.stt_ready))
        setVoiceStatus(status.detail || "")
      })
      .catch(() => {
        if (!cancelled) setSttReady(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!moreOpen) return
    let cancelled = false
    api<PermissionSnapshot>("/api/permissions")
      .then((data) => {
        if (!cancelled) setCatalog(data.permissions || [])
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [moreOpen])

  useEffect(() => {
    settledRef.current = false
    listenGenRef.current += 1
    setOwnerNote("")
    const gen = listenGenRef.current
    const prompt = (parsed?.spoken_prompt || "").trim()
    if (!prompt) return

    let cancelled = false
    void (async () => {
      await speakChatReply(prompt)
      if (cancelled || settledRef.current || gen !== listenGenRef.current) return
      await new Promise((resolve) => window.setTimeout(resolve, 400))
      if (cancelled || settledRef.current || gen !== listenGenRef.current) return
      if (sttReadyRef.current) void startListening(gen)
    })()

    return () => {
      cancelled = true
      stopListening()
      stopChatTts()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed?.spoken_prompt, taskId, pendingId])

  function stopListening() {
    if (listenTimerRef.current != null) {
      window.clearTimeout(listenTimerRef.current)
      listenTimerRef.current = null
    }
    const recorder = recorderRef.current
    if (recorder && recorder.state !== "inactive") {
      recorder.stop()
    }
    recorderRef.current = null
    setListening(false)
  }

  async function startListening(gen: number) {
    if (settledRef.current || gen !== listenGenRef.current) return
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record a spoken reply. Use the buttons, or try Chrome/Edge.")
      return
    }
    if (sttReadyRef.current === false) {
      setError(voiceStatus || "Local speech recognition is not installed. Use the buttons, or install Whisper.")
      return
    }
    stopListening()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (settledRef.current || gen !== listenGenRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      const recorder = new MediaRecorder(stream)
      const chunks: Blob[] = []
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data)
      }
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop())
        setListening(false)
        recorderRef.current = null
        if (settledRef.current || gen !== listenGenRef.current) return
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" })
        if (blob.size > 0) void handleSpokenBlob(blob, gen)
      }
      recorder.start()
      recorderRef.current = recorder
      setListening(true)
      setError("")
      listenTimerRef.current = window.setTimeout(() => {
        if (recorder.state !== "inactive") recorder.stop()
      }, LISTEN_MS)
    } catch (err: unknown) {
      setListening(false)
      setError(err instanceof Error ? err.message : "Microphone permission was denied.")
    }
  }

  async function handleSpokenBlob(blob: Blob, gen: number) {
    setBusy(true)
    try {
      const body = new FormData()
      body.append("audio", blob, "grant.webm")
      const result = await apiForm<{ transcript?: string }>("/api/voice/transcribe", body)
      if (settledRef.current || gen !== listenGenRef.current) return
      const transcript = (result.transcript || "").trim()
      const mode = interpretSpokenGrant(transcript)
      if (!mode) {
        const unclear = spokenGrantUnclearMessage()
        setError(unclear)
        if (speakChatReplies) await speakChatReply(unclear)
        return
      }
      const decideMode: ApprovalDecideMode =
        mode === "always" ? "always" : mode === "deny" ? "deny" : "allow_once"
      if (decideMode !== "deny" && requiresOwnerInput && !ownerNote.trim()) {
        setError("Type a note or instruction before allowing this step.")
        return
      }
      await submitDecision(decideMode)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not transcribe that reply.")
    } finally {
      setBusy(false)
    }
  }

  async function submitDecision(mode: ApprovalDecideMode) {
    settledRef.current = true
    listenGenRef.current += 1
    stopListening()
    stopChatTts()
    setBusy(true)
    setError("")
    const note = ownerNote.trim()
    try {
      if (usesDecideApi && onDecide) {
        await onDecide({
          mode,
          ...(note ? { owner_note: note.slice(0, OWNER_NOTE_MAX) } : {}),
        })
        onDismiss?.()
      } else if (taskId) {
        if (isPermission || parsed?.permission_id) {
          await api(`/api/tasks/${taskId}/continue`, {
            method: "POST",
            body: JSON.stringify({
              approve: mode !== "deny",
              grant_mode: mode,
              permission_id: parsed?.permission_id,
              owner_note: note ? note.slice(0, OWNER_NOTE_MAX) : undefined,
            }),
          })
        } else {
          await api(`/api/tasks/${taskId}/continue`, {
            method: "POST",
            body: JSON.stringify({
              approve: mode !== "deny",
              owner_note: note ? note.slice(0, OWNER_NOTE_MAX) : undefined,
            }),
          })
        }
      } else {
        throw new Error("No approval channel available for this prompt.")
      }
    } catch (err: unknown) {
      settledRef.current = false
      setError(err instanceof Error ? err.message : "Could not save that choice.")
    } finally {
      setBusy(false)
    }
  }

  async function saveCatalogItem(id: string, mode: string) {
    setBusy(true)
    setError("")
    try {
      const next = await api<PermissionCatalogItem>(`/api/permissions/${id}`, {
        method: "PUT",
        body: JSON.stringify({ mode }),
      })
      setCatalog((items) => items.map((item) => (item.id === id ? { ...item, ...next } : item)))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not update that permission.")
    } finally {
      setBusy(false)
    }
  }

  const title =
    parsed?.title || (parsed?.irreversible ? "Approve this deletion" : "Jarvis needs your decision")
  const detail =
    parsed?.detail ||
    parsed?.reason ||
    (parsed?.name ? `Jarvis wants to run ${parsed.name}.` : "Review this action before Jarvis continues.")
  const spoken = (parsed?.spoken_prompt || "").trim()
  const hint = parsed?.voice_reply_hint || "Say always, yes, or no."

  const groups = useMemo(() => {
    const grouped: Record<string, PermissionCatalogItem[]> = {}
    for (const item of catalog) {
      grouped[item.group] = grouped[item.group] || []
      grouped[item.group].push(item)
    }
    return grouped
  }, [catalog])

  const shellClass = `permission-prompt permission-prompt-${variant}${variant === "modal" ? " permission-prompt-overlay-card" : ""}`

  return (
    <div className={shellClass}>
      <p className="permission-prompt-kicker">Approval required</p>
      <strong className="permission-prompt-title" id={variant === "modal" ? "permission-modal-title" : undefined}>
        {title}
      </strong>
      <p className="permission-prompt-detail">{detail}</p>
      {spoken && <p className="permission-prompt-spoken">{spoken}</p>}
      {parsed?.irreversible && (
        <p className="permission-prompt-warn">This can delete or irreversibly change files.</p>
      )}
      <label className="permission-note-field">
        <span>{requiresOwnerInput ? "Your input (required)" : "Note or extra instruction (optional)"}</span>
        <textarea
          value={ownerNote}
          onChange={(event) => setOwnerNote(event.target.value.slice(0, OWNER_NOTE_MAX))}
          placeholder="Add a note or extra instruction"
          rows={3}
          disabled={busy}
        />
      </label>
      {listening && (
        <p className="permission-prompt-listening" role="status" aria-live="polite">
          Listening… {hint}
        </p>
      )}
      <div className="permission-prompt-actions">
        <button
          className="btn"
          type="button"
          disabled={busy || allowBlocked}
          onClick={() => void submitDecision("allow_once")}
        >
          Allow this time
        </button>
        <button
          className="btn secondary"
          type="button"
          disabled={busy || allowBlocked}
          onClick={() => void submitDecision("always")}
        >
          Always allow
        </button>
        <button className="btn secondary" type="button" disabled={busy} onClick={() => void submitDecision("deny")}>
          Deny
        </button>
        <button
          className="btn secondary"
          type="button"
          disabled={busy || listening}
          onClick={() => void startListening(listenGenRef.current)}
        >
          {listening ? "Listening…" : "Answer by voice"}
        </button>
        {isPermission && (
          <button
            className="permission-more-btn"
            type="button"
            aria-expanded={moreOpen}
            disabled={busy}
            onClick={() => setMoreOpen((open) => !open)}
          >
            {moreOpen ? "Less" : "More"}
          </button>
        )}
      </div>
      {moreOpen && (
        <div className="permission-more">
          <p className="permission-more-lede">
            Internet, local network, HexStrike, and blue/red flags. Red is a permission flag only — Jarvis will not
            run offensive tools.
          </p>
          {Object.entries(GROUP_LABELS).map(([group, label]) => (
            <section key={group} className="permission-group">
              <h3>{label}</h3>
              {(groups[group] || []).map((item) => (
                <label key={item.id} className="permission-row">
                  <span>
                    <strong>{item.title}</strong>
                    <em>{item.detail}</em>
                    {item.offensive && <em className="permission-lock">Flag only. No payloads.</em>}
                    {item.gated && !item.gate_unlocked && (
                      <em className="permission-lock">Locked until the {item.gated} password gate is unlocked.</em>
                    )}
                  </span>
                  <select
                    value={item.persisted || item.status}
                    disabled={busy || (Boolean(item.gated) && !item.gate_unlocked && item.offensive)}
                    onChange={(event) => void saveCatalogItem(item.id, event.target.value)}
                    aria-label={item.title}
                  >
                    <option value="ask">Ask</option>
                    <option value="always">Always</option>
                    <option value="deny">Don&apos;t allow</option>
                  </select>
                </label>
              ))}
            </section>
          ))}
        </div>
      )}
      {error && <p className="permission-prompt-error">{error}</p>}
    </div>
  )
}
