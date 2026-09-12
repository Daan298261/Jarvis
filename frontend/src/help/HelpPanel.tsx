import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { getHelpStatus, postHelpChat, type HelpStatus, type HelpTopic } from "../api"

type HelpTab = "ask" | "guides"

type ChatTurn = {
  role: "user" | "assistant"
  text: string
  usedWeb?: boolean
}

type HelpPanelProps = {
  open: boolean
  onClose: () => void
  variant: "hud" | "classic"
}

export function HelpTrigger({
  onClick,
  variant,
  expanded = false,
}: {
  onClick: () => void
  variant: "hud" | "classic"
  expanded?: boolean
}) {
  const className = variant === "hud" ? "hud-icon-btn hud-help-trigger" : "classic-help-trigger"
  return (
    <button type="button" className={className} onClick={onClick} aria-label="Open help" aria-expanded={expanded}>
      Help
    </button>
  )
}

export function HelpPanel({ open, onClose, variant }: HelpPanelProps) {
  const [tab, setTab] = useState<HelpTab>("ask")
  const [status, setStatus] = useState<HelpStatus | null>(null)
  const [topic, setTopic] = useState<HelpTopic | null>(null)
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [conversationId, setConversationId] = useState<string | undefined>()
  const [turns, setTurns] = useState<ChatTurn[]>([])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    getHelpStatus()
      .then((payload) => {
        if (!cancelled) setStatus(payload)
      })
      .catch(() => {
        if (!cancelled) setError("Help is unavailable right now.")
      })
    return () => {
      cancelled = true
    }
  }, [open])

  const topics = status?.topics || []
  const panelClass = variant === "hud" ? "hud-help-panel" : "classic-help-panel"

  const defaultHint = useMemo(
    () =>
      "Ask how to pair a phone, load a custom model, run a swarm, or change autonomy. Help reads local docs first, then the public web.",
    [],
  )

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const message = draft.trim()
    if (!message || busy) return
    setBusy(true)
    setError("")
    setDraft("")
    setTurns((current) => [...current, { role: "user", text: message }])
    try {
      const reply = await postHelpChat(message, conversationId)
      setConversationId(reply.conversation_id)
      setTurns((current) => [
        ...current,
        { role: "assistant", text: reply.text, usedWeb: reply.used_web },
      ])
    } catch (err) {
      setError(err instanceof Error ? err.message : "Help request failed.")
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return (
    <div className={panelClass} role="dialog" aria-label="Jarvis help">
      <header className={variant === "hud" ? "hud-help-head" : "classic-help-head"}>
        <strong>Help</strong>
        <span className={variant === "hud" ? "hud-help-meta" : "classic-help-meta"}>
          Docs first{status?.qwen38_9b_installed ? " · Qwen3.8 9B local" : ""}
        </span>
        <button type="button" className={variant === "hud" ? "hud-drawer-close" : "classic-help-close"} onClick={onClose} aria-label="Close help">
          ×
        </button>
      </header>

      <div className={variant === "hud" ? "hud-help-tabs" : "classic-help-tabs"}>
        <button type="button" className={tab === "ask" ? "active" : ""} onClick={() => setTab("ask")}>
          Ask
        </button>
        <button type="button" className={tab === "guides" ? "active" : ""} onClick={() => setTab("guides")}>
          Guides
        </button>
      </div>

      {tab === "ask" ? (
        <div className={variant === "hud" ? "hud-help-ask" : "classic-help-ask"}>
          <div className={variant === "hud" ? "hud-help-thread" : "classic-help-thread"}>
            {turns.length === 0 && <p className={variant === "hud" ? "hud-thread-empty" : "lede"}>{defaultHint}</p>}
            {turns.map((turn, index) => (
              <div key={`${turn.role}-${index}`} className={`help-turn help-turn-${turn.role}`}>
                <span>{turn.role === "user" ? "You" : "Help"}</span>
                <p>{turn.text}</p>
                {turn.usedWeb && <em>Included a secondary public-web note.</em>}
              </div>
            ))}
          </div>
          {error && <p className="help-error">{error}</p>}
          <form onSubmit={onSubmit} className={variant === "hud" ? "hud-help-form" : "classic-help-form"}>
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="How do I pair my phone?"
              aria-label="Help question"
              disabled={busy}
            />
            <button type="submit" disabled={busy || !draft.trim()}>
              {busy ? "…" : "Ask"}
            </button>
          </form>
        </div>
      ) : (
        <div className={variant === "hud" ? "hud-help-guides" : "classic-help-guides"}>
          {topic ? (
            <article>
              <button type="button" className="help-back" onClick={() => setTopic(null)}>
                ← All guides
              </button>
              <h2>{topic.title}</h2>
              <p>{topic.body}</p>
              <Link to={topic.href} onClick={onClose}>
                Open {topic.title}
              </Link>
            </article>
          ) : (
            <ul>
              {topics.map((item) => (
                <li key={item.id}>
                  <button type="button" onClick={() => setTopic(item)}>
                    <strong>{item.title}</strong>
                    <span>{item.summary}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
