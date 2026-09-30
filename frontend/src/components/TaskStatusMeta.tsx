import { Link } from "react-router-dom"
import type { Task } from "../api"
import { TaskHeartbeat } from "./TaskActivity"
import {
  activityLabel,
  childAggregationLabel,
  decisionInboxHref,
  formatElapsedSeconds,
  formatProgress,
  phaseBadgeClass,
  phaseLabel,
  shouldShowVerification,
  verificationBadgeClass,
  verificationLabel,
} from "../taskStatus"

type CompactProps = {
  task: Task
  /** Show live heartbeat for active tasks. Default true. */
  heartbeat?: boolean
  /** Include elapsed when no deterministic progress. Default true. */
  showElapsed?: boolean
  className?: string
}

/** Compact RFC-0026 row: phase · activity · optional progress/elapsed · verification. */
export function TaskStatusMeta({
  task,
  heartbeat = true,
  showElapsed = true,
  className = "",
}: CompactProps) {
  const phase = phaseLabel(task)
  const activity = activityLabel(task)
  const progress = formatProgress(task.progress)
  const elapsed = formatElapsedSeconds(task.elapsed_seconds ?? task.duration_seconds)
  const children = childAggregationLabel(task.child_execution)
  const showVerification = shouldShowVerification(task)
  const inboxHref = decisionInboxHref(task)
  const active = ["queued", "running", "waiting"].includes(task.state || task.status)

  return (
    <span className={`task-status-meta ${className}`.trim()}>
      {heartbeat && active && <TaskHeartbeat task={task} label={false} />}
      <span className={`badge phase-badge ${phaseBadgeClass(task)}`} title="Execution phase">
        {phase}
      </span>
      {activity && (
        <span className="task-status-activity" title={activity}>
          {activity}
        </span>
      )}
      {progress ? (
        <span className="task-status-progress" title="Deterministic progress">
          {progress}
        </span>
      ) : showElapsed && elapsed ? (
        <span className="task-status-elapsed">{elapsed}</span>
      ) : null}
      {children && <span className="task-status-children">{children}</span>}
      {task.stale_phase_warning && (
        <span className="badge waiting" title="Phase has not advanced within the expected window">
          Stale phase
        </span>
      )}
      {showVerification && (
        <span
          className={`badge verification-badge ${verificationBadgeClass(task.verification_summary)}`}
          title="Verification status (independent of lifecycle success)"
        >
          {verificationLabel(task.verification_summary)}
        </span>
      )}
      {inboxHref && (
        <Link
          className="task-status-inbox-link"
          to={inboxHref}
          onClick={(event) => event.stopPropagation()}
          title="Open Decision Inbox"
        >
          Decision Inbox
        </Link>
      )}
    </span>
  )
}

type BadgeOnlyProps = {
  task: Task
  className?: string
}

/** Lifecycle badge only — never reuse for verification. */
export function TaskLifecycleBadge({ task, className = "" }: BadgeOnlyProps) {
  const state = task.state || task.status || "queued"
  return <span className={`badge ${state} ${className}`.trim()}>{state}</span>
}

export function TaskVerificationBadge({ task, className = "" }: BadgeOnlyProps) {
  if (!shouldShowVerification(task)) return null
  return (
    <span
      className={`badge verification-badge ${verificationBadgeClass(task.verification_summary)} ${className}`.trim()}
      title="Verification status (independent of lifecycle success)"
    >
      {verificationLabel(task.verification_summary)}
    </span>
  )
}
