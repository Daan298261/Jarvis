import type { Task } from "../api"

export type OrbMood = "idle" | "listening" | "thinking" | "speaking" | "alert"

export function deriveOrbMood(
  task: Task | null | undefined,
  opts: { recording?: boolean; speaking?: boolean; systemDegraded?: boolean },
): OrbMood {
  if (opts.systemDegraded || task?.status === "failed" || task?.waiting_for_confirmation) {
    return "alert"
  }
  if (opts.recording) return "listening"
  if (opts.speaking) return "speaking"
  if (task && ["running", "queued", "waiting"].includes(task.status)) return "thinking"
  return "idle"
}
