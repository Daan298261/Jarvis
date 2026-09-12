import { useCallback, useEffect, useRef } from "react"
import { getAuthUrl, type Task } from "../api"
import { queueChatSpeech, stopChatTts, unspokenRemainder } from "./chatTtsPlayer"

type TaskEvent = NonNullable<Task["events"]>[number]

function eventKey(event: Pick<TaskEvent, "kind" | "title" | "detail" | "stage">): string {
  return `${event.kind}:${event.title}:${event.stage}:${event.detail}`
}

function appendPrefix(current: string, next: string): string {
  if (!current) return next.trim()
  if (current.endsWith(next.trim())) return current
  return `${current.trim()} ${next.trim()}`
}

/** Play stable TTS events immediately, then queue only the unspoken final remainder. */
export function useTaskSpeech(
  task: Task | null,
  enabled: boolean,
  onSpeakingChange?: (speaking: boolean) => void,
): void {
  const taskRef = useRef<Task | null>(task)
  const enabledRef = useRef(enabled)
  const onSpeakingRef = useRef(onSpeakingChange)
  const seenEventsRef = useRef(new Set<string>())
  const spokenPrefixRef = useRef("")
  const completedKeyRef = useRef("")
  const taskId = task?.id
  const taskStatus = task?.status
  const taskResult = task?.result
  const taskError = task?.error
  const taskEvents = task?.events

  useEffect(() => {
    taskRef.current = task
    enabledRef.current = enabled
    onSpeakingRef.current = onSpeakingChange
  }, [task, enabled, onSpeakingChange])

  const speakEvent = useCallback((event: TaskEvent) => {
    if (event.kind !== "chat_tts") return
    const key = eventKey(event)
    if (seenEventsRef.current.has(key)) return
    seenEventsRef.current.add(key)
    const text = (event.detail || "").trim()
    if (!text || !enabledRef.current || taskRef.current?.status === "completed") return
    if (event.title === "Speak reply") {
      spokenPrefixRef.current = appendPrefix(spokenPrefixRef.current, text)
    }
    void queueChatSpeech(text, {
      append: true,
      onStart: () => onSpeakingRef.current?.(true),
      onEnd: () => onSpeakingRef.current?.(false),
    })
  }, [])

  useEffect(() => {
    seenEventsRef.current.clear()
    spokenPrefixRef.current = ""
    completedKeyRef.current = ""
    if (!taskId) return

    const stream = new EventSource(getAuthUrl(`/api/tasks/${encodeURIComponent(taskId)}/events`))
    stream.onmessage = (message) => {
      try {
        speakEvent(JSON.parse(message.data) as TaskEvent)
      } catch {
        // Persisted task events remain the reconnect fallback.
      }
    }
    return () => stream.close()
  }, [taskId, speakEvent])

  useEffect(() => {
    for (const event of taskEvents || []) speakEvent(event)
  }, [taskEvents, speakEvent])

  useEffect(() => {
    if (!enabled) {
      stopChatTts()
      onSpeakingRef.current?.(false)
      return
    }
    if (!taskId || taskStatus !== "completed") return
    const fullText = (taskResult || taskError || "").trim()
    if (!fullText) return
    const key = `${taskId}:${fullText}`
    if (completedKeyRef.current === key) return
    completedKeyRef.current = key
    const remainder = unspokenRemainder(fullText, spokenPrefixRef.current)
    if (!remainder) return
    void queueChatSpeech(remainder, {
      append: Boolean(spokenPrefixRef.current),
      onStart: () => onSpeakingRef.current?.(true),
      onEnd: () => onSpeakingRef.current?.(false),
    })
  }, [enabled, taskId, taskStatus, taskResult, taskError])
}
