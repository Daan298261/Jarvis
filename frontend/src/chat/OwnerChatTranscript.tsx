import { useMemo, useState } from "react"
import { PermissionPrompt } from "./PermissionPrompt"
import {
  filterWorkEvents,
  isTaskRunning,
  taskStatusLine,
  visibleChatTurns,
  writeShowWorkPreference,
  type OwnerChatEvent,
} from "./ownerChatView"

type OwnerChatTranscriptProps = {
  taskId: string
  prompt?: string | null
  status: string
  stage?: string | null
  current_action?: string | null
  current_tool?: string | null
  waiting_for_confirmation?: boolean
  confirmation_payload?: unknown
  result?: string | null
  error?: string | null
  events?: OwnerChatEvent[]
  messages?: { role: string; content: string }[] | null
  pending?: string[]
  variant: "hud" | "classic"
}

export function OwnerChatTranscript({
  taskId,
  prompt,
  status,
  stage,
  current_action,
  current_tool,
  waiting_for_confirmation,
  confirmation_payload,
  result,
  error,
  events = [],
  messages,
  pending,
  variant,
}: OwnerChatTranscriptProps) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const workEvents = useMemo(() => filterWorkEvents(events), [events])
  const turns = useMemo(
    () => visibleChatTurns({ prompt, result, error, messages, pending }),
    [prompt, result, error, messages, pending],
  )
  const running = isTaskRunning(status)
  const statusLine = taskStatusLine({
    status,
    stage,
    current_action,
    current_tool,
    waiting_for_confirmation,
  })

  function toggleDetails() {
    setDetailsOpen((open) => {
      const next = !open
      writeShowWorkPreference(next)
      return next
    })
  }

  const isHud = variant === "hud"
  const userBubbleClass = isHud ? "hud-bubble hud-bubble-user" : "bubble bubble-user"
  const assistantBubbleClass = isHud ? "hud-bubble hud-bubble-assistant" : "bubble bubble-assistant"
  const userLabel = isHud ? <span className="hud-bubble-label">You</span> : <strong>You</strong>
  const assistantLabel = isHud ? <span className="hud-bubble-label">Jarvis</span> : <strong>Jarvis</strong>

  return (
    <>
      {turns.map((turn, index) => (
        <div
          className={turn.role === "user" ? userBubbleClass : assistantBubbleClass}
          key={`${turn.role}-${index}-${turn.content.slice(0, 24)}`}
        >
          {turn.role === "user" ? userLabel : assistantLabel}
          {turn.role === "user" ? <p>{turn.content}</p> : <div className="report">{turn.content}</div>}
        </div>
      ))}

      {running && statusLine && (
        <p className={isHud ? "hud-chat-status" : "chat-status-line"} aria-live="polite">
          <span className={isHud ? "hud-typing-dot" : "chat-typing-dot"} aria-hidden />
          {statusLine}
        </p>
      )}

      {waiting_for_confirmation && (
        <PermissionPrompt taskId={taskId} payload={confirmation_payload} variant={isHud ? "hud" : "classic"} />
      )}

      <div className={isHud ? "hud-chat-details" : "chat-work-details"}>
        <button
          type="button"
          className={isHud ? "hud-details-toggle" : "chat-details-toggle"}
          aria-expanded={detailsOpen}
          onClick={toggleDetails}
        >
          {detailsOpen ? "Hide work" : "Show work"}
          {!detailsOpen && workEvents.length > 0 ? ` (${workEvents.length})` : ""}
        </button>

        {detailsOpen && (
          <div className={isHud ? "hud-chat-details-panel" : "chat-work-details-panel"}>
            {isHud ? (
              workEvents.slice(-12).map((event, index) => (
                <div className="hud-bubble hud-bubble-event" key={`${event.created_at}-${index}`}>
                  <span className="hud-bubble-label">{event.title}</span>
                  {event.detail && <p>{event.detail.slice(0, 400)}</p>}
                </div>
              ))
            ) : (
              <div className="timeline">
                {workEvents.map((event, index) => (
                  <div className="t-item" key={`${event.created_at}-${index}`}>
                    <div className="rail" />
                    <div>
                      <strong>{event.title}</strong>
                      {event.detail && <p>{event.detail.slice(0, 800)}</p>}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {!workEvents.length && running && (
              <p className={isHud ? "hud-thread-empty" : "lede"}>No steps logged yet.</p>
            )}
          </div>
        )}
      </div>
    </>
  )
}
