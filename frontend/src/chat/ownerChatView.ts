import { useCallback, useState } from "react"

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

/** Events suitable for the work / details panel (drops noisy model heartbeat). */
export function filterWorkEvents(events: OwnerChatEvent[]): OwnerChatEvent[] {
  return events.filter((event) => !(event.kind === "model" && event.title === "Model is thinking"))
}

export function assistantReplyText(result?: string | null, error?: string | null): string {
  return (result || error || "").trim()
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
