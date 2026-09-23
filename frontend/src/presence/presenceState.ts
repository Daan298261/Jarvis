import type { Task } from "../api"
import type { PresencePhase, PresenceSnapshot } from "./presenceTypes"

type PresenceInputs = {
  task: Task | null
  recording: boolean
  speaking: boolean
  connected?: boolean
  systemDegraded?: boolean
  pendingApproval?: boolean
  runningTaskCount?: number
  decisionCount?: number
  audioLevel?: number
}

function phaseFor(inputs: PresenceInputs): PresencePhase {
  if (inputs.connected === false) return "offline"
  if (inputs.task?.status === "failed") return "error"
  if (inputs.task?.waiting_for_confirmation || inputs.pendingApproval) return "approval"
  if (inputs.systemDegraded) return "alert"
  if (inputs.speaking) return "speaking"
  if (inputs.recording) return "listening"
  if (inputs.task?.status === "running") return "executing"
  if (inputs.task && !["completed", "cancelled", "failed"].includes(inputs.task.status)) return "thinking"
  return "idle"
}

function intensityFor(phase: PresencePhase): number {
  switch (phase) {
    case "offline": return 0.05
    case "idle": return 0.2
    case "waiting": return 0.28
    case "listening": return 0.5
    case "thinking": return 0.62
    case "executing": return 0.72
    case "alert": return 0.78
    case "approval": return 0.5
    case "error": return 0.84
    case "speaking": return 0.92
  }
}

export function derivePresenceSnapshot(inputs: PresenceInputs): PresenceSnapshot {
  const phase = phaseFor(inputs)
  const task = inputs.task
  return {
    phase,
    intensity: intensityFor(phase),
    connected: inputs.connected !== false,
    activeTaskId: task?.id,
    activeTaskLabel: task?.title || task?.prompt?.slice(0, 72) || undefined,
    runningTaskCount: Math.max(0, inputs.runningTaskCount ?? (task?.status === "running" ? 1 : 0)),
    decisionCount: Math.max(0, inputs.decisionCount ?? (task?.waiting_for_confirmation ? 1 : 0)),
    systemDegraded: !!inputs.systemDegraded || task?.status === "failed",
    audioLevel: Math.max(0, Math.min(1, inputs.audioLevel ?? 0)),
  }
}
