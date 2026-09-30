import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api, type Task, type TaskObservability, type VerificationCheck } from "../api"
import {
  activityLabel,
  checkLabel,
  childAggregationLabel,
  decisionInboxHref,
  formatElapsedSeconds,
  formatProgress,
  humanizeToken,
  lifecycleBadgeClass,
  lifecycleLabel,
  mergeObservability,
  phaseBadgeClass,
  phaseLabel,
  shouldShowVerification,
  verificationBadgeClass,
  verificationLabel,
  verificationResultOf,
  verifierName,
} from "../taskStatus"

function clock(value?: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

function age(value?: string | null): string {
  if (!value) return "No update yet"
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

export function TaskHeartbeat({ task, label = true }: { task: Task; label?: boolean }) {
  const heartbeat = task.heartbeat_status || (task.alive ? "alive" : "stopped")
  const text = heartbeat === "alive" ? "Live" : heartbeat === "waiting" ? "Waiting" : heartbeat === "stale" ? "Stale" : "Stopped"
  return (
    <span className={`task-heartbeat ${heartbeat}`} title={task.last_heartbeat_at ? `Heartbeat ${age(task.last_heartbeat_at)}` : text}>
      <span className="task-heartbeat-dot" />
      {label && text}
    </span>
  )
}

function CheckRow({ check }: { check: string | VerificationCheck }) {
  const label = checkLabel(check)
  const result = typeof check === "string" ? "" : String(check.result || "").toLowerCase()
  const severity = typeof check === "string" ? "" : String(check.severity || "").toLowerCase()
  const tone = result === "fail" || result === "failed" || severity === "error"
    ? "fail"
    : result === "pass" || result === "passed" || result === "ok" || result === "success"
      ? "pass"
      : "info"
  const remediation = typeof check === "string" ? "" : (check.remediation || "").trim()
  return (
    <div className={`verification-check tone-${tone}`}>
      <span>{label}</span>
      {remediation && <em>Remediation: {remediation}</em>}
    </div>
  )
}

function VerificationPanel({ task }: { task: Task }) {
  const summary = task.verification_summary
  if (!shouldShowVerification(task)) return null
  const result = verificationResultOf(summary)
  const checks = summary?.checks || []
  const warnings = summary?.warnings || []
  const refs = summary?.evidence_refs || []
  const verifier = verifierName(summary)
  const fallbackEvidence = (task.verification || "").trim()
  const headline = checks.length
    ? checkLabel(checks[0])
    : warnings[0] || fallbackEvidence || (
      result === "NOT_VERIFIED"
        ? "No independent verification recorded."
        : "Verification recorded."
    )

  return (
    <details className={`verification-summary ${verificationBadgeClass(summary)}`} open={result !== "NOT_VERIFIED" || checks.length > 0}>
      <summary>
        <span className={`badge verification-badge ${verificationBadgeClass(summary)}`}>
          {verificationLabel(summary)}
        </span>
        <span className="verification-summary-line" title={headline}>{headline}</span>
      </summary>
      <div className="verification-detail">
        <div className="task-activity-grid">
          <div><b>Result</b><span>{verificationLabel(summary)}</span></div>
          <div><b>Verifier</b><span>{verifier || "—"}</span></div>
          {summary?.timestamp && <div><b>Recorded</b><span>{clock(summary.timestamp)}</span></div>}
          {summary?.answer_changed_by_verification != null && (
            <div><b>Answer changed</b><span>{summary.answer_changed_by_verification ? "yes" : "no"}</span></div>
          )}
        </div>
        {checks.length > 0 && (
          <div className="verification-checks">
            <b>Checks</b>
            {checks.map((check, index) => (
              <CheckRow key={index} check={check} />
            ))}
          </div>
        )}
        {warnings.length > 0 && (
          <div className="verification-warnings">
            <b>Warnings</b>
            {warnings.map((warning, index) => (
              <div key={index}>{warning}</div>
            ))}
          </div>
        )}
        {refs.length > 0 && (
          <div className="verification-evidence">
            <b>Evidence</b>
            {refs.map((ref, index) => (
              <div key={index} className="stat">{ref}</div>
            ))}
          </div>
        )}
        {!checks.length && fallbackEvidence && (
          <div className="verification-evidence">
            <b>Evidence</b>
            <div>{fallbackEvidence}</div>
          </div>
        )}
      </div>
    </details>
  )
}

function PhaseHistory({ task }: { task: Task }) {
  const history = task.phase_history || []
  if (!history.length) return null
  return (
    <details className="task-phase-history">
      <summary>
        <span>Phase history</span>
        <span className="task-activity-summary">{history.length} segments</span>
      </summary>
      <div className="task-recent-actions">
        {history.map((entry, index) => (
          <div key={`${entry.phase}-${entry.started_at}-${index}`}>
            <span>{clock(entry.started_at)}</span>
            <strong>{humanizeToken(entry.phase)}</strong>
            <em>
              {entry.source || "orchestrator"}
              {entry.blocking_reason ? ` · ${humanizeToken(entry.blocking_reason)}` : ""}
              {entry.ended_at ? ` → ${clock(entry.ended_at)}` : " · current"}
            </em>
          </div>
        ))}
      </div>
    </details>
  )
}

function ChildExecution({ task }: { task: Task }) {
  const child = task.child_execution
  if (!child?.child_count) return null
  const summary = childAggregationLabel(child)
  return (
    <details className="task-child-execution">
      <summary>
        <span>Child workers</span>
        <span className="task-activity-summary">{summary}</span>
      </summary>
      <div className="task-recent-actions">
        {(child.children || []).map((row, index) => (
          <div key={row.id || index}>
            <span>{humanizeToken(row.execution_phase || row.status || "—")}</span>
            <strong>{row.id || `worker-${index + 1}`}</strong>
            <em>{row.status || "—"}</em>
          </div>
        ))}
      </div>
    </details>
  )
}

export function TaskActivityPanel({
  task,
  elapsed,
  fetchObservability = true,
}: {
  task: Task
  elapsed: number
  /** When true, enrich from GET /api/tasks/{id}/observability if phase history missing. */
  fetchObservability?: boolean
}) {
  const [enriched, setEnriched] = useState<Task>(task)
  const [obsError, setObsError] = useState<string | null>(null)

  useEffect(() => {
    setEnriched(task)
    setObsError(null)
  }, [task])

  useEffect(() => {
    if (!fetchObservability) return
    const needsEnrichment = !(task.phase_history && task.phase_history.length)
    if (!needsEnrichment) return
    let cancelled = false
    void api<TaskObservability>(`/api/tasks/${encodeURIComponent(task.id)}/observability`)
      .then((obs) => {
        if (cancelled) return
        setEnriched((current) => mergeObservability(current.id === task.id ? current : task, obs))
        setObsError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const message = err instanceof Error ? err.message : "Observability unavailable"
        setObsError(message)
      })
    return () => {
      cancelled = true
    }
  }, [task.id, task.phase_history, task.updated_at, fetchObservability])

  const view = enriched
  const active = ["queued", "running", "waiting"].includes(view.state || view.status)
  const recent = (view.events || []).slice(-10).reverse()
  const activity = activityLabel(view) || "Waiting for activity"
  const progress = formatProgress(view.progress)
  const phaseElapsed = formatElapsedSeconds(view.phase_elapsed_seconds)
  const inboxHref = decisionInboxHref(view)
  const external = view.external_wait

  return (
    <details className="task-activity" open={active}>
      <summary>
        <span className="task-activity-head">
          <TaskHeartbeat task={view} />
          <span className={`badge phase-badge ${phaseBadgeClass(view)}`}>{phaseLabel(view)}</span>
          <span className={`badge ${lifecycleBadgeClass(view)}`} title="Lifecycle state">{lifecycleLabel(view)}</span>
        </span>
        <span className="task-activity-summary">{activity}</span>
      </summary>
      <div className="task-activity-grid">
        <div><b>Lifecycle</b><span>{lifecycleLabel(view)}</span></div>
        <div><b>Phase</b><span>{phaseLabel(view)}</span></div>
        <div><b>Started</b><span>{clock(view.started_at || view.created_at)}</span></div>
        <div><b>Elapsed</b><span>{elapsed}s{phaseElapsed ? ` · phase ${phaseElapsed}` : ""}</span></div>
        <div><b>Worker</b><span>{view.active_worker || "Jarvis agent"}</span></div>
        {progress && <div><b>Progress</b><span>{progress}</span></div>}
        <div className="span-2">
          <b>Current activity</b>
          <span>
            {activity}
            {view.current_tool ? ` · ${view.current_tool}` : ""}
          </span>
        </div>
        <div><b>Last progress</b><span>{age(view.last_progress_at)}</span></div>
        <div><b>Heartbeat</b><span>{age(view.last_heartbeat_at)}</span></div>
        {view.stale_phase_warning && (
          <div className="span-2">
            <b>Stale phase</b>
            <span>
              Phase has not advanced within {formatElapsedSeconds(view.stale_phase_threshold_seconds) || "the expected window"}.
              Observability signal only — not automatic failure.
            </span>
          </div>
        )}
        {external && (
          <div className="span-2">
            <b>External wait</b>
            <span>
              {humanizeToken(external.kind || "other")}
              {external.detail ? ` — ${external.detail}` : ""}
            </span>
          </div>
        )}
        {inboxHref && (
          <div className="span-2">
            <b>Approval</b>
            <span>
              Waiting for approval.{" "}
              <Link to={inboxHref}>Open Decision Inbox</Link>
              {view.decision_inbox_item_id ? ` · ${view.decision_inbox_item_id}` : ""}
              {view.decision_inbox_link_error?.message ? ` · ${view.decision_inbox_link_error.message}` : ""}
            </span>
          </div>
        )}
      </div>
      {obsError && <p className="lede task-obs-error">Observability enrich failed: {obsError}</p>}
      {recent.length > 0 && (
        <div className="task-recent-actions">
          <b>Recent activity</b>
          {recent.map((event, index) => (
            <div key={`${event.created_at}-${index}`}>
              <span>{clock(event.created_at)}</span>
              <strong>{event.title}</strong>
              <em>
                {event.phase ? `${humanizeToken(event.phase)} · ` : ""}
                {event.source || "jarvis-agent"}
              </em>
            </div>
          ))}
        </div>
      )}
      <PhaseHistory task={view} />
      <ChildExecution task={view} />
      <VerificationPanel task={view} />
    </details>
  )
}
