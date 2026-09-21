import { useEffect, useId, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { speakChatReply } from "../tts/chatTtsPlayer"
import { healthSpokenSummary, type HealthIssue } from "./systemHealth"

type HudLocalStatusProps = {
  statusOnline: boolean
  issues: HealthIssue[]
}

export function HudLocalStatus({ statusOnline, issues }: HudLocalStatusProps) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const lastSpoken = useRef("")

  useEffect(() => {
    if (!issues.length) {
      lastSpoken.current = ""
      setOpen(false)
      return
    }
    const spoken = healthSpokenSummary(issues)
    if (!spoken || spoken === lastSpoken.current) return
    lastSpoken.current = spoken
    setOpen(true)
    void speakChatReply(spoken)
  }, [issues])

  const label = statusOnline ? "LOCAL · ONLINE" : "LOCAL · DEGRADED"

  return (
    <div className={`hud-local-status${statusOnline ? "" : " degraded"}`}>
      <button
        type="button"
        className={`hud-local-state${statusOnline ? "" : " degraded"}`}
        aria-expanded={open}
        aria-controls={panelId}
        title={statusOnline ? "Local systems" : "Show why Jarvis is degraded"}
        onClick={() => setOpen((value) => !value)}
      >
        {label}
        <span className="hud-local-caret" aria-hidden>
          {open ? "▴" : "▾"}
        </span>
      </button>
      {open && (
        <div className="hud-local-status-panel" id={panelId} role="status">
          {issues.length === 0 ? (
            <p>Local systems are responding.</p>
          ) : (
            <ul>
              {issues.map((issue) => (
                <li key={issue.id}>
                  <strong>{issue.title}</strong>
                  <span>{issue.detail}</span>
                  {issue.href ? <Link to={issue.href}>Open</Link> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
