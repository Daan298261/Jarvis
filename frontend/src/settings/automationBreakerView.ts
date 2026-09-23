/** RFC-0071 portal view helpers. Runtime checks stay fail-closed: bad payloads are rejected. */

export const BREAKER_ACTIVE = "ACTIVE"
export const BREAKER_DEGRADED = "DEGRADED"
export const BREAKER_DISABLED_BY_FAILURE = "DISABLED_BY_FAILURE"

export const BREAKER_THRESHOLD_MIN = 1
export const BREAKER_THRESHOLD_MAX = 100

const KNOWN_BREAKER_STATES = new Set([
  BREAKER_ACTIVE,
  BREAKER_DEGRADED,
  BREAKER_DISABLED_BY_FAILURE,
])

const AUTH_MASK = "There's a setup problem. Jarvis is working on a fix."

const AUDIT_DETAIL_KEYS = [
  "consecutive_failure_count",
  "failure_threshold",
  "trigger",
  "run_id",
  "task_id",
  "reason",
  "last_failure_summary",
  "acknowledged",
]

const AUDIT_LABELS: Record<string, string> = {
  breaker_tripped: "Breaker tripped",
  trigger_suppressed: "Trigger suppressed",
  failure_counter_reset: "Failure counter reset",
  reenable: "Re-enabled",
  reenable_idempotent: "Re-enable (already active)",
  threshold_updated: "Threshold updated",
}

export type AutomationFailedRun = {
  task_or_run_id: string
}

export type AutomationBreakerView = {
  automation_id: string
  consecutive_failure_count: number
  failure_threshold: number
  last_failure_at: string | null
  last_failure_summary: string
  breaker_state: string
  disabled_at: string | null
  recent_failed_runs: AutomationFailedRun[]
  kind: string
  ref_id: string
  updated_at: string
}

export type AutomationBreakerAuditEvent = {
  id: string
  event_type: string
  automation_id: string
  actor: string
  timestamp: string
  detail: Record<string, unknown>
}

export type BreakerAction = "list" | "audit" | "reenable" | "threshold"

export class BreakerViewError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "BreakerViewError"
  }
}

export function isKnownBreakerState(state: string): boolean {
  return KNOWN_BREAKER_STATES.has(state)
}

export function canReenableBreaker(state: string): boolean {
  return state === BREAKER_DISABLED_BY_FAILURE
}

export function breakerBadgeClass(state: string): string {
  if (state === BREAKER_ACTIVE) return "ok"
  if (state === BREAKER_DEGRADED) return "waiting"
  if (state === BREAKER_DISABLED_BY_FAILURE) return "failed"
  return "queued"
}

export function breakerStateCaption(state: string): string {
  if (state === BREAKER_ACTIVE) return "Eligible to run. Consecutive failures are clear."
  if (state === BREAKER_DEGRADED) return "Failures are still under the threshold. Automatic triggers still run."
  if (state === BREAKER_DISABLED_BY_FAILURE) {
    return "Automatic triggers are suppressed until an owner re-enables this automation."
  }
  return "Unrecognized breaker state. This automation is not confirmed healthy."
}

export function failureSummaryText(row: Pick<
  AutomationBreakerView,
  "breaker_state" | "consecutive_failure_count" | "last_failure_summary"
>): string {
  const text = row.last_failure_summary.trim()
  if (text) return text
  if (row.breaker_state === BREAKER_ACTIVE && row.consecutive_failure_count === 0) {
    return "No failure recorded."
  }
  return "No failure summary was returned."
}

export function formatBreakerTimestamp(value: string | null | undefined): string {
  if (!value) return "Not recorded"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function parseThresholdInput(raw: string): number | null {
  const trimmed = raw.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const value = Number(trimmed)
  if (value < BREAKER_THRESHOLD_MIN || value > BREAKER_THRESHOLD_MAX) return null
  return value
}

export function breakerAuditLabel(eventType: string): string {
  return AUDIT_LABELS[eventType] || eventType.replaceAll("_", " ")
}

export function formatAuditDetail(detail: Record<string, unknown>): string {
  const extras = Object.keys(detail).filter((key) => !AUDIT_DETAIL_KEYS.includes(key))
  const keys = [...AUDIT_DETAIL_KEYS.filter((key) => key in detail), ...extras]
  const parts: string[] = []
  for (const key of keys) {
    const value = detail[key]
    if (value == null || value === "") continue
    if (typeof value === "object") continue
    parts.push(`${key.replaceAll("_", " ")}: ${String(value)}`)
  }
  return parts.join(" · ")
}

export function auditEventsForAutomation(
  events: AutomationBreakerAuditEvent[],
  automationId: string,
  limit = 6,
): AutomationBreakerAuditEvent[] {
  return events.filter((event) => event.automation_id === automationId).slice(0, limit)
}

export function parseAutomationBreaker(raw: unknown): AutomationBreakerView | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  const row = raw as Record<string, unknown>
  const automationId = typeof row.automation_id === "string" ? row.automation_id.trim() : ""
  if (!automationId) return null
  if (!Number.isInteger(row.consecutive_failure_count) || Number(row.consecutive_failure_count) < 0) {
    return null
  }
  if (
    !Number.isInteger(row.failure_threshold)
    || Number(row.failure_threshold) < BREAKER_THRESHOLD_MIN
    || Number(row.failure_threshold) > BREAKER_THRESHOLD_MAX
  ) {
    return null
  }
  if (typeof row.breaker_state !== "string" || !row.breaker_state.trim()) return null
  const lastFailureAt = optionalText(row.last_failure_at)
  const disabledAt = optionalText(row.disabled_at)
  if (lastFailureAt === undefined || disabledAt === undefined) return null
  if (row.last_failure_summary != null && typeof row.last_failure_summary !== "string") return null
  if (row.kind != null && typeof row.kind !== "string") return null
  if (row.ref_id != null && typeof row.ref_id !== "string") return null
  if (row.updated_at != null && typeof row.updated_at !== "string") return null
  const failed = parseFailedRuns(row)
  if (!failed) return null
  return {
    automation_id: automationId,
    consecutive_failure_count: Number(row.consecutive_failure_count),
    failure_threshold: Number(row.failure_threshold),
    last_failure_at: lastFailureAt,
    last_failure_summary: typeof row.last_failure_summary === "string" ? row.last_failure_summary : "",
    breaker_state: row.breaker_state,
    disabled_at: disabledAt,
    recent_failed_runs: failed,
    kind: typeof row.kind === "string" ? row.kind : "",
    ref_id: typeof row.ref_id === "string" ? row.ref_id : "",
    updated_at: typeof row.updated_at === "string" ? row.updated_at : "",
  }
}

export function parseBreakerList(payload: unknown): AutomationBreakerView[] {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new BreakerViewError("Breaker list response did not include automations.")
  }
  const automations = (payload as { automations?: unknown }).automations
  if (!Array.isArray(automations)) {
    throw new BreakerViewError("Breaker list response did not include automations.")
  }
  return automations.map((item, index) => {
    const parsed = parseAutomationBreaker(item)
    if (!parsed) {
      throw new BreakerViewError(`Breaker list item ${index + 1} was missing required state.`)
    }
    return parsed
  })
}

export function parseBreakerAudit(payload: unknown): AutomationBreakerAuditEvent[] {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new BreakerViewError("Breaker audit response did not include events.")
  }
  const events = (payload as { events?: unknown }).events
  if (!Array.isArray(events)) {
    throw new BreakerViewError("Breaker audit response did not include events.")
  }
  return events.map((item, index) => {
    const parsed = parseAuditEvent(item)
    if (!parsed) {
      throw new BreakerViewError(`Breaker audit event ${index + 1} was missing required fields.`)
    }
    return parsed
  })
}

export function breakerFailureMessage(err: unknown, action: BreakerAction): string {
  if (err instanceof BreakerViewError) return err.message
  const status = readStatus(err)
  const detail = usableDetail(err instanceof Error ? err.message : "")
  if (status === 401) {
    return "Owner private key required (401). Add the owner key in Settings → Network, then try again."
  }
  if (status === 403) {
    if (action === "reenable") {
      return detail
        ? `Re-enable refused (403). ${detail}`
        : "Re-enable refused (403). Owner authorization is required, and an automation cannot re-enable itself."
    }
    if (action === "threshold") {
      return detail
        ? `Threshold update refused (403). ${detail}`
        : "Threshold update refused (403). Owner authorization is required."
    }
    return detail ? `Request refused (403). ${detail}` : "Request refused (403)."
  }
  if (status === 400) {
    return detail ? `Request rejected (400). ${detail}` : "Request rejected (400)."
  }
  if (status === 404) return "Automation breaker record was not found (404)."
  if (status === 422) {
    return detail
      ? `Request rejected (422). ${detail}`
      : "Request rejected (422). Threshold must be a whole number from 1 to 100."
  }
  if (action === "list") {
    return detail ? `Could not load automation breakers. ${detail}` : "Could not load automation breakers."
  }
  if (action === "audit") {
    return detail ? `Could not load breaker audit. ${detail}` : "Could not load breaker audit."
  }
  if (action === "reenable") {
    return detail ? `Re-enable failed. ${detail}` : "Re-enable failed."
  }
  if (action === "threshold") {
    return detail ? `Threshold update failed. ${detail}` : "Threshold update failed."
  }
  return detail || "Automation breaker request failed."
}

function optionalText(value: unknown): string | null | undefined {
  if (value == null || value === "") return null
  if (typeof value !== "string") return undefined
  return value
}

function parseFailedRuns(row: Record<string, unknown>): AutomationFailedRun[] | null {
  const runs = row.recent_failed_runs
  const ids = row.recent_failed_run_ids
  if (runs != null && !Array.isArray(runs)) return null
  if (ids != null && !Array.isArray(ids)) return null
  if (Array.isArray(runs) && runs.length > 0) {
    const parsed = collectRunObjects(runs)
    if (!parsed) return null
    return parsed
  }
  if (Array.isArray(ids)) return collectRunIds(ids)
  if (Array.isArray(runs)) return []
  return []
}

function collectRunObjects(runs: unknown[]): AutomationFailedRun[] | null {
  const out: AutomationFailedRun[] = []
  for (const item of runs) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null
    const id = (item as { task_or_run_id?: unknown }).task_or_run_id
    if (typeof id !== "string" || !id.trim()) return null
    out.push({ task_or_run_id: id.trim() })
  }
  return out
}

function collectRunIds(ids: unknown[]): AutomationFailedRun[] | null {
  const out: AutomationFailedRun[] = []
  for (const id of ids) {
    if (typeof id !== "string" || !id.trim()) return null
    out.push({ task_or_run_id: id.trim() })
  }
  return out
}

function parseAuditEvent(raw: unknown): AutomationBreakerAuditEvent | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  const row = raw as Record<string, unknown>
  if (typeof row.id !== "string" || !row.id.trim()) return null
  if (typeof row.event_type !== "string" || !row.event_type.trim()) return null
  if (typeof row.automation_id !== "string" || !row.automation_id.trim()) return null
  if (row.actor != null && typeof row.actor !== "string") return null
  if (row.timestamp != null && typeof row.timestamp !== "string") return null
  if (row.detail != null && (typeof row.detail !== "object" || Array.isArray(row.detail))) return null
  return {
    id: row.id,
    event_type: row.event_type,
    automation_id: row.automation_id,
    actor: typeof row.actor === "string" && row.actor.trim() ? row.actor : "system",
    timestamp: typeof row.timestamp === "string" ? row.timestamp : "",
    detail: row.detail && typeof row.detail === "object" && !Array.isArray(row.detail)
      ? row.detail as Record<string, unknown>
      : {},
  }
}

function readStatus(err: unknown): number | null {
  if (!err || typeof err !== "object" || !("status" in err)) return null
  const status = Number((err as { status: unknown }).status)
  return Number.isInteger(status) ? status : null
}

function usableDetail(message: string): string {
  const trimmed = message.trim()
  if (!trimmed || trimmed === AUTH_MASK) return ""
  return trimmed
}
