import { useCallback, useEffect, useState } from "react"
import { getAuthUrl } from "../api"

export const SHOW_WORK_STORAGE_KEY = "jarvis.chat.showWork"

export type OwnerChatEvent = {
  kind: string
  title: string
  detail: string
  stage: string
  created_at: string
}

export function readShowWorkPreference(): boolean {
  try {
    return localStorage.getItem(SHOW_WORK_STORAGE_KEY) === "true"
  } catch {
    return false
  }
}

export function writeShowWorkPreference(showWork: boolean): void {
  try {
    localStorage.setItem(SHOW_WORK_STORAGE_KEY, showWork ? "true" : "false")
  } catch {
    // Best-effort preference.
  }
}

export function useShowWorkPreference(): [boolean, (showWork: boolean) => void] {
  const [showWork, setShowWork] = useState(() => readShowWorkPreference())
  const persist = useCallback((next: boolean) => {
    writeShowWorkPreference(next)
    setShowWork(next)
  }, [])
  return [showWork, persist]
}

const HIDDEN_WORK_TITLES = new Set(["Model is thinking", "Reasoning complete", "Thinking"])
const HIDDEN_WORK_KINDS = new Set(["assistant_delta", "chat_tts"])
const DEEPER_RESULT_LABEL = "Deeper result"

export function mergeAssistantTexts(front: string, worker: string): string {
  const left = (front || "").trim()
  const right = (worker || "").trim()
  if (!left) return right
  if (!right || left === right || right.startsWith(left) || left.includes(right)) return right || left
  if (left.toLowerCase().includes(DEEPER_RESULT_LABEL.toLowerCase())) return `${left}\n\n${right}`
  return `${left}\n\n${DEEPER_RESULT_LABEL}\n${right}`
}

/** Events suitable for the work / details panel (drops noisy model heartbeat). */
export function filterWorkEvents(events: OwnerChatEvent[]): OwnerChatEvent[] {
  return events.filter(
    (event) => !HIDDEN_WORK_TITLES.has(event.title) && !HIDDEN_WORK_KINDS.has(event.kind),
  )
}

/** Heartbeat / reasoning lines — separate collapsible stream from tool work. */
export function filterThoughtEvents(events: OwnerChatEvent[]): OwnerChatEvent[] {
  return events.filter((event) => HIDDEN_WORK_TITLES.has(event.title))
}

const INTERNAL_LINE = /^(?:\*\*)?(?:VERIFICATION|PLAN|END STATE|ACCEPTANCE CRITERIA|DIAGNOSIS|OBSERVATION)\b/i
const PSEUDO_USER_LINE = /^(?:User|Human|You):\s+/i

export function splitAssistantContent(content: string): { public: string; internal: string } {
  const publicLines: string[] = []
  const internalLines: string[] = []
  for (const line of (content || "").split("\n")) {
    const trimmed = line.trim()
    if (!trimmed) {
      if (internalLines.length && internalLines[internalLines.length - 1] !== "") {
        internalLines.push("")
      } else if (publicLines.length) {
        publicLines.push(line)
      }
      continue
    }
    if (PSEUDO_USER_LINE.test(trimmed) || INTERNAL_LINE.test(trimmed)) {
      internalLines.push(line)
      continue
    }
    if (internalLines.length && !publicLines.length) {
      internalLines.push(line)
      continue
    }
    publicLines.push(line)
  }
  return { public: publicLines.join("\n").trim(), internal: internalLines.join("\n").trim() }
}

export function assistantReplyText(result?: string | null, error?: string | null): string {
  return (result || error || "").trim()
}

export type ChatTurn = {
  role: "user" | "assistant"
  content: string
  internal?: string
  public?: string
}

const FOLLOW_UP_MARKER = "\n\nFollow-up: "
const CONTINUE_PREFIX = "Continue the existing task."

export function stripContinueWrapper(text: string): string {
  const raw = (text || "").trim()
  if (!raw.startsWith(CONTINUE_PREFIX)) return raw
  const split = raw.indexOf("\n\n")
  if (split >= 0) return raw.slice(split + 2).trim()
  return ""
}

export function visibleChatTurns(input: {
  prompt?: string | null
  result?: string | null
  error?: string | null
  messages?: { role: string; content: string }[] | null
  pending?: string[]
  liveAssistant?: string | null
}): ChatTurn[] {
  const turns: ChatTurn[] = []
  const fromApi = (input.messages || []).filter((item) => item.role === "user" || item.role === "assistant")
  if (fromApi.length) {
    for (const item of fromApi) {
      const content = stripContinueWrapper(item.content || "")
      if (!content) continue
      const role: ChatTurn["role"] = item.role === "assistant" ? "assistant" : "user"
      const last = turns[turns.length - 1]
      if (role === "assistant") {
        const split = splitAssistantContent(content)
        const publicText = split.public || (!split.internal ? content : "")
        if (!publicText && !split.internal) continue
        if (last && last.role === role) {
          if (last.content === publicText && last.internal === split.internal) continue
          last.content = mergeAssistantTexts(last.content, publicText)
          last.public = last.content
          last.internal = [last.internal, split.internal].filter(Boolean).join("\n") || undefined
          continue
        }
        turns.push({ role, content: publicText, public: publicText, internal: split.internal || undefined })
        continue
      }
      if (last && last.role === role && last.content === content) continue
      turns.push({ role, content })
    }
  } else {
    const blob = (input.prompt || "").trim()
    if (blob) {
      for (const part of blob.split(FOLLOW_UP_MARKER)) {
        const content = part.trim()
        if (content) turns.push({ role: "user", content })
      }
    }
    const reply = assistantReplyText(input.result, input.error)
    if (reply) turns.push({ role: "assistant", content: reply })
  }
  const live = (input.liveAssistant || "").trim()
  if (live) {
    const last = turns[turns.length - 1]
    if (!last || last.role === "user") {
      turns.push({ role: "assistant", content: live, public: live })
    } else if (last.role === "assistant" && live.startsWith(last.content) && live !== last.content) {
      last.content = live
      last.public = live
    }
  }
  const knownUsers = new Set(turns.filter((item) => item.role === "user").map((item) => item.content))
  for (const pending of input.pending || []) {
    const content = pending.trim()
    if (content && !knownUsers.has(content)) {
      turns.push({ role: "user", content })
      knownUsers.add(content)
    }
  }
  return turns
}

export function prunePendingUserTexts(
  pending: string[],
  input: Omit<Parameters<typeof visibleChatTurns>[0], "pending">,
): string[] {
  const known = new Set(
    visibleChatTurns({ ...input, pending: [] })
      .filter((item) => item.role === "user")
      .map((item) => item.content.trim()),
  )
  return pending.filter((text) => {
    const content = text.trim()
    return Boolean(content) && !known.has(content)
  })
}

export function isTaskRunning(status: string): boolean {
  return ["running", "queued", "waiting"].includes(status)
}

export function taskStatusLine(task: {
  status: string
  stage?: string | null
  current_action?: string | null
  current_tool?: string | null
  waiting_for_confirmation?: boolean
}): string {
  if (task.waiting_for_confirmation) return "Waiting for your approval"
  if (task.current_action) return task.current_action
  if (task.current_tool) return `Using ${task.current_tool}…`
  if (task.stage) return task.stage
  if (isTaskRunning(task.status)) return "Working…"
  return ""
}

function frontEventText(event: { kind?: string; detail?: string }): string {
  const kind = event.kind || ""
  const detail = (event.detail || "").trim()
  if (kind === "assistant_delta") return detail
  if (kind === "front_response_completed" && detail) {
    try {
      const parsed = JSON.parse(detail) as { text?: string }
      if (parsed && typeof parsed.text === "string") return parsed.text
    } catch {
      return detail
    }
  }
  return ""
}

/** Live first-token preview from the task event stream (front lane + worker). */
export function useLiveAssistantPreview(taskId: string, running: boolean): string {
  const [text, setText] = useState("")
  useEffect(() => {
    if (!taskId || !running) {
      return
    }
    let acc = ""
    const stream = new EventSource(getAuthUrl(`/api/tasks/${encodeURIComponent(taskId)}/events`))
    stream.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as { kind?: string; detail?: string }
        const chunk = frontEventText(event)
        if (!chunk) return
        if (event.kind === "front_response_completed") {
          acc = chunk
        } else {
          acc += chunk
        }
        setText(acc)
      } catch {
        // Keep the last good preview.
      }
    }
    return () => stream.close()
  }, [taskId, running])
  return running ? text : ""
}
