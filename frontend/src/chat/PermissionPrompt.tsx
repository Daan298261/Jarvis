import { useEffect, useMemo, useRef, useState } from "react"
import { api, apiForm } from "../api"
import { useSpeakChatReplies } from "../tts/chatTtsSettings"
import { speakChatReply, stopChatTts } from "../tts/chatTtsPlayer"
import { interpretSpokenGrant, spokenGrantUnclearMessage } from "./spokenGrant"
import "./permissionPrompt.css"

export type PermissionCatalogItem = {
  id: string
  group: string
  title: string
  detail: string
  status: string
  persisted: string
  gated?: string | null
  offensive?: boolean
  gate_unlocked?: boolean
  reason?: string
}

export type ConfirmationPayload = {
  kind?: string
  id?: string
  name?: string
  arguments?: Record<string, unknown>
  irreversible?: boolean
  permission_id?: string
  pending?: string[]
  title?: string
  detail?: string
  reason?: string
  options?: string[]
  catalog?: PermissionCatalogItem[]
  spoken_prompt?: string
  voice_reply_hint?: string
}

type PermissionSnapshot = {
  permissions: PermissionCatalogItem[]
  groups: Record<string, PermissionCatalogItem[]>
}

type PermissionPromptProps = {
  taskId: string
  payload?: unknown
  variant?: "hud" | "classic" | "phone"
}

const GROUP_LABELS: Record<string, string> = {
  computer: "Computer use",
  network: "Network",
  cyber: "Cybersecurity suite",
  blue: "Blue team (defensive)",
  red: "Red team (flags only)",
}

const LISTEN_MS = 8000

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

export function PermissionPrompt({ taskId, payload, variant = "classic" }: PermissionPromptProps) {
  const parsed = useMemo(() => parseConfirmationPayload(payload), [payload])
  const isPermission = parsed?.kind === "permission" || Boolean(parsed?.permission_id)
  const [moreOpen, setMoreOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
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
    // Speak once per prompt payload; Answer by voice remains available if STT was not ready yet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed?.spoken_prompt, taskId])

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
      if (isPermission) {
        await grant(mode)
      } else {
        await continueTask({ approve: mode !== "deny" })
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not transcribe that reply.")
    } finally {
      setBusy(false)
    }
  }

  async function continueTask(body: Record<string, unknown>) {
    settledRef.current = true
    listenGenRef.current += 1
    stopListening()
    stopChatTts()
    setBusy(true)
    setError("")
    try {
      await api(`/api/tasks/${taskId}/continue`, {
        method: "POST",
        body: JSON.stringify(body),
      })
    } catch (err: unknown) {
      settledRef.current = false
      setError(err instanceof Error ? err.message : "Could not save that choice.")
    } finally {
      setBusy(false)
    }
  }

  async function grant(mode: "allow_once" | "allow_session" | "always" | "deny") {
    await continueTask({
      approve: mode !== "deny",
      grant_mode: mode,
      permission_id: parsed?.permission_id,
    })
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

  const title = parsed?.title || (parsed?.irreversible ? "Approve this deletion" : "Jarvis needs permission")
  const detail =
    parsed?.detail ||
    parsed?.reason ||
    (parsed?.name ? `Jarvis wants to run ${parsed.name}.` : "Review this action before Jarvis continues.")
  const spoken = (parsed?.spoken_prompt || "").trim()
  const hint = parsed?.voice_reply_hint || (isPermission ? "Say yes, always, or no." : "Say yes or no.")

  const groups = useMemo(() => {
    const grouped: Record<string, PermissionCatalogItem[]> = {}
    for (const item of catalog) {
      grouped[item.group] = grouped[item.group] || []
      grouped[item.group].push(item)
    }
    return grouped
  }, [catalog])

  return (
    <div className={`permission-prompt permission-prompt-${variant}`}>
      <p className="permission-prompt-kicker">Permission required</p>
      <strong className="permission-prompt-title">{title}</strong>
      <p className="permission-prompt-detail">{detail}</p>
      {spoken && <p className="permission-prompt-spoken">{spoken}</p>}
      {parsed?.irreversible && (
        <p className="permission-prompt-warn">This can delete or irreversibly change files.</p>
      )}
      {listening && (
        <p className="permission-prompt-listening" role="status" aria-live="polite">
          Listening… {hint}
        </p>
      )}
      {isPermission ? (
        <div className="permission-prompt-actions">
          <button className="btn" type="button" disabled={busy} onClick={() => void grant("allow_once")}>
            Allow once
          </button>
          <button className="btn secondary" type="button" disabled={busy} onClick={() => void grant("always")}>
            Always allow
          </button>
          <button className="btn secondary" type="button" disabled={busy} onClick={() => void grant("deny")}>
            Don&apos;t allow
          </button>
          <button
            className="btn secondary"
            type="button"
            disabled={busy || listening}
            onClick={() => void startListening(listenGenRef.current)}
          >
            {listening ? "Listening…" : "Answer by voice"}
          </button>
          <button
            className="permission-more-btn"
            type="button"
            aria-expanded={moreOpen}
            disabled={busy}
            onClick={() => setMoreOpen((open) => !open)}
          >
            {moreOpen ? "Less" : "More"}
          </button>
        </div>
      ) : (
        <div className="permission-prompt-actions">
          <button
            className="btn danger"
            type="button"
            disabled={busy}
            onClick={() => void continueTask({ approve: true })}
          >
            Approve
          </button>
          <button
            className="btn secondary"
            type="button"
            disabled={busy}
            onClick={() => void continueTask({ approve: false })}
          >
            Reject
          </button>
          <button
            className="btn secondary"
            type="button"
            disabled={busy || listening}
            onClick={() => void startListening(listenGenRef.current)}
          >
            {listening ? "Listening…" : "Answer by voice"}
          </button>
        </div>
      )}
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
          <button
            className="btn secondary"
            type="button"
            disabled={busy}
            onClick={() => void grant("allow_session")}
          >
            Allow this session, then continue
          </button>
        </div>
      )}
      {error && <p className="permission-prompt-error">{error}</p>}
    </div>
  )
}
