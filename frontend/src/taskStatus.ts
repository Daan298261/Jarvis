import type {
  Task,
  TaskObservability,
  TaskProgressUnits,
  VerificationCheck,
  VerificationResult,
  VerificationSummary,
} from "./api"

const TERMINAL_LIFECYCLE = new Set(["completed", "failed", "cancelled"])

export function humanizeToken(value?: string | null): string {
  if (!value) return ""
  return value.toLowerCase().replaceAll("_", " ").trim()
}

/** Execution phase label — distinct from lifecycle `state`/`status`. */
export function phaseLabel(task: Pick<Task, "execution_phase" | "state" | "status">): string {
  const phase = task.execution_phase
  if (phase) return humanizeToken(phase)
  return humanizeToken(task.state || task.status || "queued") || "queued"
}

export function lifecycleLabel(task: Pick<Task, "state" | "status">): string {
  return humanizeToken(task.state || task.status || "queued") || "queued"
}

export function lifecycleBadgeClass(task: Pick<Task, "state" | "status">): string {
  return task.state || task.status || "queued"
}

export function phaseBadgeClass(task: Pick<Task, "execution_phase" | "state" | "status">): string {
  const phase = (task.execution_phase || "").toUpperCase()
  if (phase === "FAILED" || phase === "CANCELLED") return "failed"
  if (phase === "COMPLETED") return "completed"
  if (phase === "DEGRADED" || phase === "WAITING_APPROVAL" || phase === "WAITING_EXTERNAL" || phase === "RECOVERING") {
    return "waiting"
  }
  if (phase === "QUEUED") return "queued"
  if (phase) return "running"
  return lifecycleBadgeClass(task)
}

/** Prefer concrete `current_activity` over generic Running… / Thinking…. */
export function activityLabel(
  task: Pick<Task, "current_activity" | "current_action" | "current_tool" | "stage" | "execution_phase" | "waiting_for_confirmation">,
): string {
  const activity = (task.current_activity || "").trim()
  if (activity && !/^thinking/i.test(activity)) return activity
  const action = (task.current_action || "").trim()
  if (action && !/^thinking/i.test(action)) return action
  if (task.waiting_for_confirmation || (task.execution_phase || "").toUpperCase() === "WAITING_APPROVAL") {
    return "Waiting for approval"
  }
  const tool = (task.current_tool || "").trim()
  if (tool) return `Running ${tool}`
  const stage = (task.stage || "").trim()
  if (stage) return humanizeToken(stage)
  return ""
}

export function formatElapsedSeconds(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return ""
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total}s`
  if (total < 3600) {
    const m = Math.floor(total / 60)
    const s = total % 60
    return s ? `${m}m ${s}s` : `${m}m`
  }
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  return m ? `${h}h ${m}m` : `${h}h`
}

export function formatProgress(progress?: TaskProgressUnits | null): string {
  if (!progress) return ""
  const { completed_units, total_units, unit_type } = progress
  if (
    typeof completed_units !== "number"
    || typeof total_units !== "number"
    || total_units <= 0
    || completed_units < 0
    || completed_units > total_units
    || !unit_type
  ) {
    return ""
  }
  const unit = humanizeToken(unit_type) || "units"
  return `${completed_units} / ${total_units} ${unit}`
}

export function formatPercentProgress(progress?: TaskProgressUnits | null): string {
  // Only when denominator exists — never invent LLM %.
  const label = formatProgress(progress)
  if (!label || !progress) return ""
  const pct = Math.round((progress.completed_units / progress.total_units) * 100)
  return `${label} (${pct}%)`
}

export function verifierName(summary?: VerificationSummary | null): string {
  if (!summary?.verifier) return ""
  if (typeof summary.verifier === "string") return summary.verifier.trim()
  return String(summary.verifier.name || summary.verifier.type || "").trim()
}

export function checkLabel(check: string | VerificationCheck): string {
  if (typeof check === "string") return check.trim()
  const type = (check.type || "").trim()
  const target = (check.target || "").trim()
  const result = (check.result || "").trim()
  const head = [type, target].filter(Boolean).join(" · ")
  const evidence = (check.evidence || "").trim()
  if (head && result && evidence) return `${head}: ${result} — ${evidence}`
  if (head && result) return `${head}: ${result}`
  if (head && evidence) return `${head} — ${evidence}`
  if (evidence) return evidence
  if (result) return result
  return head || "Check"
}

export function verificationResultOf(summary?: VerificationSummary | null): VerificationResult {
  return String(summary?.result || "NOT_VERIFIED").toUpperCase()
}

export function verificationLabel(summary?: VerificationSummary | null): string {
  return humanizeToken(verificationResultOf(summary)) || "not verified"
}

export function verificationBadgeClass(summary?: VerificationSummary | null): string {
  const result = verificationResultOf(summary)
  if (result === "VERIFIED") return "verified"
  if (result === "VERIFICATION_FAILED") return "verification-failed"
  if (result === "PARTIALLY_VERIFIED") return "partially-verified"
  return "not-verified"
}

/** Show verification on terminal tasks always; on active tasks only when evidence exists. */
export function shouldShowVerification(
  task: Pick<Task, "state" | "status" | "verification_summary" | "verification">,
): boolean {
  const summary = task.verification_summary
  const result = verificationResultOf(summary)
  const lifecycle = String(task.state || task.status || "").toLowerCase()
  if (TERMINAL_LIFECYCLE.has(lifecycle)) return true
  if (!summary) return Boolean(task.verification)
  if (result !== "NOT_VERIFIED") return true
  const checks = summary.checks || []
  const warnings = summary.warnings || []
  const refs = summary.evidence_refs || []
  return checks.length > 0 || warnings.length > 0 || refs.length > 0 || Boolean(task.verification)
}

export function decisionInboxHref(task: Pick<Task, "decision_inbox_item_id" | "execution_phase" | "waiting_for_confirmation">): string | null {
  const phase = (task.execution_phase || "").toUpperCase()
  if (phase !== "WAITING_APPROVAL" && !task.waiting_for_confirmation) return null
  if (task.decision_inbox_item_id) return "/coding"
  return "/coding"
}

export function childAggregationLabel(child?: Task["child_execution"]): string {
  if (!child || !child.child_count) return ""
  const parts: string[] = []
  if (child.active_workers) parts.push(`${child.active_workers} active`)
  if (child.waiting_workers) parts.push(`${child.waiting_workers} waiting`)
  if (!parts.length) parts.push(`${child.child_count} workers`)
  const dominant = child.dominant_phase ? humanizeToken(child.dominant_phase) : ""
  return dominant ? `${dominant} — ${parts.join(", ")}` : parts.join(", ")
}

export function compactStatusLine(task: Task): string {
  const phase = phaseLabel(task)
  const activity = activityLabel(task)
  const progress = formatProgress(task.progress)
  const elapsed = formatElapsedSeconds(task.elapsed_seconds ?? task.duration_seconds)
  const bits = [phase]
  if (activity) bits.push(activity)
  if (progress) bits.push(progress)
  else if (elapsed) bits.push(elapsed)
  return bits.join(" · ")
}

export type TaskStatusSlice = Pick<
  Task,
  | "execution_phase"
  | "state"
  | "status"
  | "current_activity"
  | "current_action"
  | "current_tool"
  | "stage"
  | "waiting_for_confirmation"
  | "verification_summary"
  | "verification"
  | "progress"
  | "elapsed_seconds"
  | "duration_seconds"
  | "decision_inbox_item_id"
  | "stale_phase_warning"
  | "child_execution"
>

export function mergeObservability(task: Task, obs: TaskObservability | null | undefined): Task {
  if (!obs) return task
  return {
    ...task,
    execution_phase: obs.execution_phase ?? task.execution_phase,
    current_activity: obs.current_activity ?? task.current_activity,
    current_action: obs.current_action ?? task.current_action,
    progress: obs.progress ?? task.progress,
    phase_history: obs.phase_history ?? task.phase_history,
    verification_summary: obs.verification_summary ?? task.verification_summary,
    external_wait: obs.external_wait ?? task.external_wait,
    decision_inbox_item: obs.decision_inbox_item ?? task.decision_inbox_item,
    decision_inbox_item_id: obs.decision_inbox_item_id ?? task.decision_inbox_item_id,
    decision_inbox_link_error: obs.decision_inbox_link_error ?? task.decision_inbox_link_error,
    phase_started_at: obs.phase_started_at ?? task.phase_started_at,
    phase_elapsed_seconds: obs.phase_elapsed_seconds ?? task.phase_elapsed_seconds,
    stale_phase_warning: obs.stale_phase_warning ?? task.stale_phase_warning,
    stale_phase_threshold_seconds: obs.stale_phase_threshold_seconds ?? task.stale_phase_threshold_seconds,
    child_execution: obs.child_execution ?? task.child_execution,
  }
}
