import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { api } from "../api"
import { OwnerChatTranscript } from "../chat/OwnerChatTranscript"

type OwnerChatPageProps = {
  variant: "hud" | "classic"
}

type ConversationDetail = {
  conversation_id?: string
  id?: string
  title?: string
  task_id?: string
  messages?: { role: string; content: string }[]
}

export function OwnerChatPage({ variant }: OwnerChatPageProps) {
  const { conversationId } = useParams()
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    const load = async () => {
      try {
        const fromOwner = await api<ConversationDetail>(`/api/owner/chat/conversations/${conversationId}`)
        if (cancelled) return
        if (fromOwner.messages?.length) {
          setDetail(fromOwner)
          setError("")
          return
        }
        const fromProjects = await api<ConversationDetail>(`/api/projects/conversations/${conversationId}`)
        if (!cancelled) {
          setDetail(fromProjects)
          setError("")
        }
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not open this chat")
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [conversationId])

  const messages = detail?.messages || []
  const title = detail?.title || "Saved chat"

  if (variant === "hud") {
    return (
      <div className="hud-chat">
        <div className="hud-thread" aria-live="polite">
          {error && <p className="hud-thread-empty">{error}</p>}
          {!error && !detail && <p className="hud-thread-empty">Loading chat…</p>}
          {detail && (
            <OwnerChatTranscript
              key={conversationId}
              variant="hud"
              taskId={conversationId || ""}
              prompt={title}
              status="completed"
              messages={messages}
            />
          )}
        </div>
      </div>
    )
  }

  return (
    <div>
      <h1>{title}</h1>
      {error && <p className="lede">{error}</p>}
      {detail && (
        <OwnerChatTranscript
          key={conversationId}
          variant="classic"
          taskId={conversationId || ""}
          prompt={title}
          status="completed"
          messages={messages}
        />
      )}
    </div>
  )
}
