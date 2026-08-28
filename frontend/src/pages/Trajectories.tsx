import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  api,
  emitNativeTrajectory,
  formatTrajectoryError,
  getTrajectory,
  importCursorTrajectory,
  listPendingTrajectories,
  listTrajectories,
  type PendingTrajectoryItem,
  type Task,
  type TrajectoryCandidateSkill,
  type TrajectoryEvent,
  type TrajectoryInspect,
  type TrajectorySummary,
} from "../api"

const SECRET_KEY_RE = /(password|passwd|secret|token|api[_-]?key|credential|auth|bearer|private[_-]?key)/i
const BEARER_RE = /Bearer\s+[A-Za-z0-9._~+/=-]+/gi
const AWS_KEY_RE = /AKIA[0-9A-Z]{16}/g
const GH_TOKEN_RE = /ghp_[A-Za-z0-9]{20,}/g
const SK_PREFIX_RE = /\bsk-[A-Za-z0-9]{20,}\b/g
const REDACTED = "[REDACTED]"

const EVENT_LABELS: Record<string, string> = {
  user_message: "You asked",
  assistant_message: "Agent replied",
  tool_call: "Used a tool",
  tool_result: "Tool result",
  verification: "Check",
  outcome: "Result",
  recovery: "Recovery",
  action: "Action",
}

const HARNESS_LABELS: Record<string, string> = {
  cursor: "Cursor",
  jarvis: "Jarvis on this PC",
}

function isSecretKey(key: string): boolean {
  return SECRET_KEY_RE.test(key)
}

function redactString(value: string): string {
  if (!value) return value
  return value
    .replace(BEARER_RE, `Bearer ${REDACTED}`)
    .replace(AWS_KEY_RE, REDACTED)
    .replace(GH_TOKEN_RE, REDACTED)
    .replace(SK_PREFIX_RE, REDACTED)
}

function sanitizeValue(value: unknown, key?: string): unknown {
  if (key && isSecretKey(key)) return REDACTED
  if (typeof value === "string") return redactString(value)
  if (Array.isArray(value)) return value.map((item) => sanitizeValue(item))
  if (value && typeof value === "object") {
    const cleaned: Record<string, unknown> = {}
    for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>)) {
      cleaned[childKey] = sanitizeValue(childValue, childKey)
    }
    return cleaned
  }
  return value
}

function sanitizeEvent(event: TrajectoryEvent): TrajectoryEvent {
  const args = event.tool_args && typeof event.tool_args === "object" ? event.tool_args : null
  const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {}
  return {
    ...event,
    content: typeof event.content === "string" ? redactString(event.content) : event.content,
    tool_result: typeof event.tool_result === "string" ? redactString(event.tool_result) : event.tool_result,
    tool_args: args ? (sanitizeValue(args) as Record<string, unknown>) : args,
    metadata: sanitizeValue(metadata) as Record<string, unknown>,
  }
}

function sanitizeInspect(detail: TrajectoryInspect): TrajectoryInspect {
  return {
    ...detail,
    goal: typeof detail.goal === "string" ? redactString(detail.goal) : detail.goal,
    recovery: typeof detail.recovery === "string" ? redactString(detail.recovery) : detail.recovery,
    failures: (detail.failures || []).map((item) => redactString(item)),
    events: [...(detail.events || [])]
      .map(sanitizeEvent)
      .sort((a, b) => a.sequence - b.sequence || a.timestamp.localeCompare(b.timestamp)),
    verification: detail.verification
      ? {
          ...detail.verification,
          details:
            typeof detail.verification.details === "string"
              ? redactString(detail.verification.details)
              : detail.verification.details,
        }
      : detail.verification,
    candidate_skills: (detail.candidate_skills || []).map((skill) => ({
      ...skill,
      name: typeof skill.name === "string" ? redactString(skill.name) : skill.name,
      description: typeof skill.description === "string" ? redactString(skill.description) : skill.description,
    })),
    provenance: {
      ...detail.provenance,
      source_uri:
        typeof detail.provenance?.source_uri === "string"
          ? redactString(detail.provenance.source_uri)
          : detail.provenance?.source_uri,
    },
  }
}

function compactDisplay(value: unknown): string {
  if (value == null || value === "") return ""
  if (typeof value === "string") return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function eventLabel(eventType: string): string {
  return EVENT_LABELS[eventType] || eventType.replaceAll("_", " ") || "Event"
}

function harnessLabel(harness: string | null | undefined): string {
  const key = (harness || "").toLowerCase()
  return HARNESS_LABELS[key] || harness || "Unknown source"
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function taskLabel(task: Task): string {
  return task.title || task.prompt?.slice(0, 72) || task.id
}

function outcomeBadge(status: string | null | undefined, verified?: boolean): string {
  const key = (status || "").toLowerCase()
  if (verified) return "completed"
  if (key === "completed" || key === "ok" || key === "success") return "waiting"
  if (key === "failed" || key === "error") return "failed"
  return "queued"
}

function outcomeLabel(status: string | null | undefined): string {
  const key = (status || "").toLowerCase()
  if (key === "completed") return "Finished"
  if (key === "failed") return "Failed"
  if (key === "attempted") return "Attempted"
  return status || "Unknown"
}

function yesNo(value: boolean | null | undefined): string {
  if (value === true) return "Yes"
  if (value === false) return "No"
  return "—"
}

function errorMessage(err: unknown, fallback: string): string {
  const formatted = formatTrajectoryError(err)
  return formatted || fallback
}

function EvidenceBanner({ trusted }: { trusted?: boolean }) {
  if (trusted) {
    return (
      <div className="card traj-banner trusted" role="status">
        <p className="license-kicker">From this PC</p>
        <p className="lede" style={{ margin: 0 }}>
          This record came from Jarvis on this PC. It is a log of what happened — it does not grant
          new capabilities or change policy.
        </p>
      </div>
    )
  }
  return (
    <div className="card traj-banner untrusted" role="status">
      <p className="license-kicker">Untrusted evidence</p>
      <p className="lede" style={{ margin: 0 }}>
        Imported records are untrusted evidence until checked. They do not grant capabilities or
        change policy. Skills stay on Memory.
      </p>
    </div>
  )
}

function ArgsBlock({ args }: { args: Record<string, unknown> | null | undefined }) {
  if (!args || !Object.keys(args).length) return null
  const entries = Object.entries(args)
  return (
    <div className="kv traj-args">
      {entries.map(([key, value]) => (
        <FragmentPair key={key} label={key} value={isSecretKey(key) ? REDACTED : compactDisplay(sanitizeValue(value, key))} />
      ))}
    </div>
  )
}

function FragmentPair({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <>
      <b>{label}</b>
      <span className="stat">{value}</span>
    </>
  )
}

function EventCard({ event }: { event: TrajectoryEvent }) {
  const args = event.tool_args && typeof event.tool_args === "object" ? event.tool_args : null
  const result = event.tool_result ? redactString(event.tool_result) : ""
  const content = event.content ? redactString(event.content) : ""
  const failed = event.success === false
  const ok = event.success === true
  return (
    <div className="t-item">
      <div className="rail" />
      <div>
        <strong>
          {eventLabel(event.event_type)}
          {event.tool_name ? ` · ${event.tool_name}` : ""}
        </strong>
        <p className="traj-event-when">{formatWhen(event.timestamp)}</p>
        {content ? <p>{content}</p> : null}
        <ArgsBlock args={args} />
        {result ? <p>{result}</p> : null}
        {ok && <span className="badge completed">Ok</span>}
        {failed && <span className="badge failed">Failed</span>}
      </div>
    </div>
  )
}

function SkillEvidence({ skill }: { skill: TrajectoryCandidateSkill }) {
  const tools = (skill.tools || []).filter(Boolean)
  return (
    <div className="traj-skill">
      <strong>{skill.name ? redactString(skill.name) : "Suggested lesson"}</strong>
      {skill.description ? <p className="lede" style={{ margin: "4px 0 0" }}>{redactString(skill.description)}</p> : null}
      <p className="lede" style={{ margin: "4px 0 0" }}>
        {tools.length ? tools.join(" → ") : "No tools listed"}
        {skill.confidence != null ? ` · confidence ${Math.round(skill.confidence * 100)}%` : ""}
      </p>
    </div>
  )
}

function TrajectoryInspectView({
  detail,
  error,
  onBack,
}: {
  detail: TrajectoryInspect | null
  error: string
  onBack: () => void
}) {
  const events = detail?.events || []
  const workspace = detail?.workspace
  const outcome = detail?.outcome
  const verification = detail?.verification
  const trusted = Boolean(detail?.provenance?.trusted)
  const skills = detail?.candidate_skills || []
  const failures = detail?.failures || []

  return (
    <div className="traj-page">
      <p className="lede" style={{ marginBottom: 12 }}>
        <button className="btn secondary" type="button" onClick={onBack}>
          All records
        </button>
      </p>
      <h1>Record</h1>
      <p className="lede">
        How this run went, in order. Outcome is what was attempted. Checked means a later test
        passed — they are not the same thing.
      </p>

      {error && (
        <div className="card traj-banner bad" role="alert">
          {error}
        </div>
      )}

      {!detail && !error && (
        <div className="card">
          <p className="lede" style={{ margin: 0 }}>Loading this record…</p>
        </div>
      )}

      {detail && (
        <>
          <EvidenceBanner trusted={trusted} />

          <div className="card" style={{ marginTop: 16 }}>
            <h2>{detail.goal || "Untitled run"}</h2>
            <div className="kv">
              <b>Source</b>
              <span>{harnessLabel(detail.provenance?.harness)}</span>
              <b>Model</b>
              <span>{detail.provenance?.model || "—"}</span>
              <b>Repository</b>
              <span>{workspace?.repository || "—"}</span>
              <b>Branch</b>
              <span className="stat">{workspace?.branch || "—"}</span>
              <b>Folder</b>
              <span className="stat">{workspace?.workspace_path || "—"}</span>
              <b>Where it came from</b>
              <span>{detail.provenance?.source_uri || detail.provenance?.source_format || "—"}</span>
              <b>Saved</b>
              <span>{formatWhen(detail.provenance?.imported_at)}</span>
              <b>Trust</b>
              <span>
                <span className={`badge ${trusted ? "completed" : "waiting"}`}>
                  {trusted ? "Trusted on this PC" : "Untrusted"}
                </span>
              </span>
              <b>Kind of work</b>
              <span>{detail.task_class || "—"}</span>
              {detail.duration_seconds != null && Number.isFinite(detail.duration_seconds) && (
                <>
                  <b>Duration</b>
                  <span>{Math.round(detail.duration_seconds)}s</span>
                </>
              )}
            </div>
          </div>

          <div className="grid two" style={{ marginTop: 16 }}>
            <div className="card">
              <p className="license-kicker">Outcome</p>
              <h2>What was attempted</h2>
              <div className="kv">
                <b>Result</b>
                <span>
                  <span className={`badge ${outcomeBadge(outcome?.status, outcome?.verified)}`}>
                    {outcomeLabel(outcome?.status)}
                  </span>
                </span>
                <b>Attempted</b>
                <span>{yesNo(outcome?.attempted)}</span>
                <b>Summary</b>
                <span>{outcome?.summary ? redactString(outcome.summary) : "—"}</span>
              </div>
            </div>
            <div className="card">
              <p className="license-kicker">Checked</p>
              <h2>What was verified</h2>
              <div className="kv">
                <b>Checked</b>
                <span>{yesNo(verification?.attempted ?? outcome?.verified)}</span>
                <b>Passed</b>
                <span>
                  <span className={`badge ${verification?.passed || outcome?.verified ? "completed" : "queued"}`}>
                    {yesNo(verification?.passed ?? outcome?.verified)}
                  </span>
                </span>
                <b>Details</b>
                <span>{verification?.details ? redactString(verification.details) : "—"}</span>
              </div>
            </div>
          </div>

          {(failures.length > 0 || detail.recovery) && (
            <div className="card" style={{ marginTop: 16 }}>
              <h2>Problems and recovery</h2>
              {failures.length === 0 && <p className="lede">No failures recorded.</p>}
              {failures.map((item) => (
                <p className="lede" key={item} style={{ margin: "0 0 6px" }}>
                  {redactString(item)}
                </p>
              ))}
              {detail.recovery && (
                <p className="lede" style={{ margin: failures.length ? "8px 0 0" : 0 }}>
                  Recovery: {redactString(detail.recovery)}
                </p>
              )}
            </div>
          )}

          <div className="card" style={{ marginTop: 16 }}>
            <h2>Suggested lessons</h2>
            <p className="lede">
              These are notes from the run. They are not skills and they do not change what Jarvis
              may do. Promote real skills from Memory after repeated success.
            </p>
            {skills.length === 0 && <p className="lede">No suggested lessons on this record.</p>}
            {skills.map((skill, index) => (
              <SkillEvidence key={`${skill.name || "skill"}-${index}`} skill={skill} />
            ))}
          </div>

          <div className="card" style={{ marginTop: 16 }}>
            <h2>Events in order</h2>
            <p className="lede">{events.length ? `${events.length} steps` : "No events on this record."}</p>
            {events.length > 0 && (
              <div className="timeline">
                {events.map((event, index) => (
                  <EventCard key={`${event.sequence}-${event.event_type}-${index}`} event={event} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export function TrajectoriesPage() {
  const { trajectoryId } = useParams()
  const navigate = useNavigate()
  const [rows, setRows] = useState<TrajectorySummary[]>([])
  const [pending, setPending] = useState<PendingTrajectoryItem[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [detail, setDetail] = useState<TrajectoryInspect | null>(null)
  const [transcript, setTranscript] = useState("")
  const [sourceUri, setSourceUri] = useState("")
  const [importModel, setImportModel] = useState("")
  const [repository, setRepository] = useState("")
  const [branch, setBranch] = useState("")
  const [workspacePath, setWorkspacePath] = useState("")
  const [taskId, setTaskId] = useState("")
  const [emitModel, setEmitModel] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  const loadList = useCallback(async () => {
    const [listed, queue, recent] = await Promise.allSettled([
      listTrajectories(100),
      listPendingTrajectories(),
      api<Task[]>("/api/tasks"),
    ])
    if (listed.status === "fulfilled") setRows(listed.value)
    else throw listed.reason
    setPending(queue.status === "fulfilled" ? queue.value : [])
    setTasks(recent.status === "fulfilled" ? recent.value : [])
  }, [])

  useEffect(() => {
    let cancelled = false
    if (trajectoryId) {
      setError("")
      setDetail(null)
      getTrajectory(trajectoryId)
        .then((payload) => {
          if (!cancelled) setDetail(sanitizeInspect(payload))
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setDetail(null)
            setError(errorMessage(err, "That record could not be opened."))
          }
        })
      return () => {
        cancelled = true
      }
    }
    loadList().catch((err: unknown) => {
      if (!cancelled) setError(errorMessage(err, "Could not load records."))
    })
    return () => {
      cancelled = true
    }
  }, [trajectoryId, loadList])

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === taskId.trim()),
    [tasks, taskId],
  )

  async function onImport(event: FormEvent) {
    event.preventDefault()
    const paste = transcript
    if (!paste.trim()) {
      setError("Paste a Cursor transcript first.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const result = await importCursorTrajectory({
        transcript: paste,
        source_uri: sourceUri.trim() || undefined,
        model: importModel.trim() || undefined,
        repository: repository.trim() || undefined,
        branch: branch.trim() || undefined,
        workspace_path: workspacePath.trim() || undefined,
      })
      setTranscript("")
      setMsg(
        result.trusted
          ? "Saved."
          : "Saved as untrusted evidence. It does not grant capabilities or change policy.",
      )
      await loadList()
      navigate(`/trajectories/${encodeURIComponent(result.trajectory_id)}`)
    } catch (err: unknown) {
      setError(errorMessage(err, "That transcript could not be imported."))
    } finally {
      setBusy(false)
    }
  }

  async function onEmit(event: FormEvent) {
    event.preventDefault()
    const id = taskId.trim()
    if (!id) {
      setError("Choose or paste a task first.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const result = await emitNativeTrajectory({
        task_id: id,
        model: emitModel.trim() || undefined,
      })
      setMsg("Recorded this PC’s run. It does not grant new capabilities or change policy.")
      await loadList()
      navigate(`/trajectories/${encodeURIComponent(result.trajectory_id)}`)
    } catch (err: unknown) {
      setError(errorMessage(err, "This task has no saved Jarvis run to record. Finish a task on this PC first, then try again."))
    } finally {
      setBusy(false)
    }
  }

  if (trajectoryId) {
    return (
      <TrajectoryInspectView
        detail={detail}
        error={error}
        onBack={() => {
          setError("")
          setDetail(null)
          navigate("/trajectories")
        }}
      />
    )
  }

  return (
    <div className="traj-page">
      <h1>Trajectories</h1>
      <p className="lede">
        Records of how a run went — from Cursor, or from Jarvis on this PC. Imported records are
        untrusted evidence. They do not grant capabilities or change policy. Skills stay on{" "}
        <Link to="/memory">Memory</Link>.
      </p>

      <EvidenceBanner trusted={false} />

      {error && (
        <div className="card traj-banner bad" role="alert" style={{ marginTop: 16 }}>
          {error}
        </div>
      )}
      {msg && (
        <div className="card traj-banner ok" role="status" style={{ marginTop: 16 }}>
          {msg}
        </div>
      )}

      <form className="card grid" style={{ marginTop: 16 }} onSubmit={onImport} autoComplete="off">
        <h2>Import from Cursor</h2>
        <p className="lede" style={{ margin: "0 0 4px" }}>
          Paste a Cursor transcript. It is sent to this PC, then the paste is cleared. Credential-looking
          fields are redacted before saving. The import stays untrusted.
        </p>
        <label>
          Cursor transcript
          <textarea
            className="field"
            rows={8}
            value={transcript}
            spellCheck={false}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            aria-label="Cursor transcript"
            placeholder={"Paste a Cursor JSONL transcript here"}
            onChange={(event) => setTranscript(event.target.value)}
          />
        </label>
        <div className="env-create-row">
          <label>
            Source (optional)
            <input
              type="text"
              value={sourceUri}
              autoComplete="off"
              placeholder="Where this export came from"
              aria-label="Source"
              onChange={(event) => setSourceUri(event.target.value)}
            />
          </label>
          <label>
            Model (optional)
            <input
              type="text"
              value={importModel}
              autoComplete="off"
              placeholder="Model name if you know it"
              aria-label="Model"
              onChange={(event) => setImportModel(event.target.value)}
            />
          </label>
        </div>
        <div className="env-create-row">
          <label>
            Repository (optional)
            <input
              type="text"
              value={repository}
              autoComplete="off"
              placeholder="owner/repo"
              aria-label="Repository"
              onChange={(event) => setRepository(event.target.value)}
            />
          </label>
          <label>
            Branch (optional)
            <input
              type="text"
              value={branch}
              autoComplete="off"
              placeholder="branch name"
              aria-label="Branch"
              onChange={(event) => setBranch(event.target.value)}
            />
          </label>
        </div>
        <label>
          Folder on disk (optional)
          <input
            type="text"
            value={workspacePath}
            autoComplete="off"
            placeholder="Workspace path"
            aria-label="Workspace path"
            onChange={(event) => setWorkspacePath(event.target.value)}
          />
        </label>
        <div className="row">
          <button className="btn" type="submit" disabled={busy}>
            Save import
          </button>
          <button
            className="btn secondary"
            type="button"
            disabled={busy || !transcript}
            onClick={() => setTranscript("")}
          >
            Clear paste
          </button>
        </div>
      </form>

      <form className="card grid" style={{ marginTop: 16 }} onSubmit={onEmit} autoComplete="off">
        <h2>Record a Jarvis task</h2>
        <p className="lede" style={{ margin: "0 0 4px" }}>
          Pick a recent task from this portal, or paste its id. Jarvis saves the same record format.
          If this task has no finished run yet, you will see a plain explanation — nothing else changes.
        </p>
        <label>
          Recent tasks
          <select
            value={tasks.some((task) => task.id === taskId) ? taskId : ""}
            aria-label="Recent tasks"
            onChange={(event) => setTaskId(event.target.value)}
          >
            <option value="">Choose a recent task</option>
            {tasks.slice(0, 40).map((task) => (
              <option key={task.id} value={task.id}>
                {taskLabel(task)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Task id
          <input
            type="text"
            value={taskId}
            autoComplete="off"
            placeholder="Or paste a task id"
            aria-label="Task id"
            onChange={(event) => setTaskId(event.target.value)}
          />
        </label>
        {selectedTask && (
          <p className="lede" style={{ margin: 0 }}>
            Selected: {taskLabel(selectedTask)} · {selectedTask.status}
          </p>
        )}
        <label>
          Model (optional)
          <input
            type="text"
            value={emitModel}
            autoComplete="off"
            placeholder="Model name if you know it"
            aria-label="Native model"
            onChange={(event) => setEmitModel(event.target.value)}
          />
        </label>
        <div className="row">
          <button className="btn" type="submit" disabled={busy}>
            Record this task
          </button>
        </div>
      </form>

      {pending.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Waiting to be learned from</h2>
          <p className="lede">
            These records are queued as evidence. They still do not grant capabilities or change
            policy.
          </p>
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>Record</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((item) => (
                <tr key={item.trajectory_id}>
                  <td>{harnessLabel(item.harness)}</td>
                  <td>
                    <Link to={`/trajectories/${encodeURIComponent(item.trajectory_id)}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>Saved records</h2>
          <button
            className="btn secondary"
            type="button"
            disabled={busy}
            onClick={() => {
              setError("")
              loadList().catch((err: unknown) => setError(errorMessage(err, "Could not load records.")))
            }}
          >
            Refresh
          </button>
        </div>
        {rows.length === 0 ? (
          <p className="lede">Nothing saved yet. Import a Cursor transcript or record a Jarvis task.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Goal</th>
                <th>Source</th>
                <th>Result</th>
                <th>Checked</th>
                <th>Trust</th>
                <th>Events</th>
                <th>Saved</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.trajectory_id}
                  className="traj-row"
                  onClick={() => navigate(`/trajectories/${encodeURIComponent(row.trajectory_id)}`)}
                >
                  <td>
                    <Link
                      to={`/trajectories/${encodeURIComponent(row.trajectory_id)}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {row.goal ? redactString(row.goal) : "Untitled run"}
                    </Link>
                  </td>
                  <td>
                    {harnessLabel(row.harness)}
                    {row.model ? ` · ${row.model}` : ""}
                  </td>
                  <td>
                    <span className={`badge ${outcomeBadge(row.outcome_status, row.outcome_verified)}`}>
                      {outcomeLabel(row.outcome_status)}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${row.outcome_verified ? "completed" : "queued"}`}>
                      {row.outcome_verified ? "Checked" : "Not checked"}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${row.trusted ? "completed" : "waiting"}`}>
                      {row.trusted ? "Trusted" : "Untrusted"}
                    </span>
                  </td>
                  <td>{row.event_count ?? "—"}</td>
                  <td>{formatWhen(row.imported_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
