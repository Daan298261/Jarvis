import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  approveCodingTask,
  cleanupCodingTask,
  codingIntegrationBlocked,
  completeCodingTask,
  formatCodingError,
  getCodingOverview,
  getCodingTask,
  integrateCodingTask,
  listCodingDecisionInbox,
  listCodingTasks,
  resolveCodingDecisionInboxItem,
  startCodingTask,
  type CodingCompleteResult,
  type CodingDecisionInboxItem,
  type CodingIntegrateResult,
  type CodingOverview,
  type CodingTaskDiff,
  type CodingTaskRecord,
} from "../api"

const TASK_STATUS_COPY: Record<string, string> = {
  active: "Isolated",
  completed: "Recorded",
  discarded: "Cleaned up",
}

const INTEGRATION_COPY: Record<string, string> = {
  pending: "Needs approval",
  awaiting_approval: "Needs approval",
  approved: "Approved — not merged",
  blocked: "Blocked",
  ready: "Candidate ready — not merged",
}

const KIND_COPY: Record<string, string> = {
  merge_conflict: "Merge conflict",
  conflict: "Conflict",
}

const INTEGRATE_CONFIRM =
  "Integrate does not merge into the trusted branch. Jarvis only prepares a candidate after verifier or human approval. Nothing lands silently. Continue?"

const CLEANUP_CONFIRM =
  "Remove this isolated worktree? The primary checkout is not touched. This cannot be undone."

function taskStatusLabel(status: string): string {
  return TASK_STATUS_COPY[status] || status || "—"
}

function taskStatusClass(status: string): string {
  const key = (status || "").toLowerCase()
  if (key === "active") return "running"
  if (key === "completed") return "completed"
  if (key === "discarded") return "queued"
  return "queued"
}

function integrationLabel(status: string, approved: boolean): string {
  if (approved && (!status || status === "pending")) return INTEGRATION_COPY.approved
  return INTEGRATION_COPY[status] || status || "Needs approval"
}

function integrationClass(status: string, approved: boolean): string {
  const key = (status || "").toLowerCase()
  if (key === "blocked") return "failed"
  if (key === "ready") return "waiting"
  if (key === "approved" || approved) return "waiting"
  return "queued"
}

function kindLabel(kind: string): string {
  return KIND_COPY[kind] || kind.replaceAll("_", " ") || "Decision"
}

function inboxStatusClass(status: string): string {
  const key = (status || "").toLowerCase()
  if (key === "open") return "waiting"
  if (key === "resolved") return "completed"
  return "queued"
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function shortSha(value: string | null | undefined): string {
  if (!value) return "—"
  return value.length > 12 ? `${value.slice(0, 12)}…` : value
}

function prettyJson(value: unknown): string {
  if (value == null) return "—"
  if (typeof value === "string") return value || "—"
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function testsSummary(tests: Record<string, unknown> | undefined): string {
  if (!tests || !Object.keys(tests).length) return "None recorded"
  if (typeof tests.passed === "boolean") {
    const notes = typeof tests.notes === "string" && tests.notes.trim() ? ` — ${tests.notes.trim()}` : ""
    return `${tests.passed ? "Passed" : "Not passed"}${notes}`
  }
  return prettyJson(tests)
}

function hasDiff(diff: CodingTaskDiff | undefined): boolean {
  if (!diff) return false
  return Boolean(diff.stat || diff.files || diff.base || diff.head)
}

function relatedInbox(
  items: CodingDecisionInboxItem[],
  taskId: string,
): CodingDecisionInboxItem[] {
  return items.filter((item) => item.task_id === taskId || item.related_task_id === taskId)
}

export function CodingPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<CodingTaskRecord[]>([])
  const [detail, setDetail] = useState<CodingTaskRecord | null>(null)
  const [inbox, setInbox] = useState<CodingDecisionInboxItem[]>([])
  const [overview, setOverview] = useState<CodingOverview | null>(null)
  const [activeOnly, setActiveOnly] = useState(true)
  const [openOnly, setOpenOnly] = useState(true)
  const [newTaskId, setNewTaskId] = useState("")
  const [repo, setRepo] = useState("")
  const [approver, setApprover] = useState("human")
  const [testsPassed, setTestsPassed] = useState(false)
  const [testsNotes, setTestsNotes] = useState("")
  const [resolutionDrafts, setResolutionDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")
  const [integrateResult, setIntegrateResult] = useState<CodingIntegrateResult | null>(null)

  const selectedId = taskId || ""

  const refreshList = useCallback(async () => {
    const data = await listCodingTasks(activeOnly)
    setTasks(data.tasks || [])
  }, [activeOnly])

  const refreshInbox = useCallback(async () => {
    const data = await listCodingDecisionInbox(openOnly)
    setInbox(data.items || [])
  }, [openOnly])

  const refreshDetail = useCallback(async (id: string) => {
    const task = await getCodingTask(id)
    setDetail(task)
  }, [])

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        await Promise.all([refreshList(), refreshInbox()])
        if (!cancelled) setError((current) => (current.startsWith("Could not load") ? "" : current))
      } catch (err: unknown) {
        if (!cancelled) setError(formatCodingError(err) || "Could not load coding isolation.")
      }
    }
    tick()
    const id = window.setInterval(tick, 8000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [refreshList, refreshInbox])

  useEffect(() => {
    getCodingOverview()
      .then(setOverview)
      .catch(() => setOverview(null))
  }, [])

  useEffect(() => {
    setIntegrateResult(null)
    setTestsPassed(false)
    setTestsNotes("")
    setApprover("human")
    setError("")
    setMsg("")
  }, [selectedId])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let cancelled = false
    const tick = async () => {
      try {
        await refreshDetail(selectedId)
        if (!cancelled) setError("")
      } catch (err: unknown) {
        if (!cancelled) {
          setDetail(null)
          setError(formatCodingError(err) || "Could not open this coding task.")
        }
      }
    }
    tick()
    const id = window.setInterval(tick, 8000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [selectedId, refreshDetail])

  const selected = detail || tasks.find((item) => item.task_id === selectedId) || null
  const selectedInbox = useMemo(
    () => (selectedId ? relatedInbox(inbox, selectedId) : inbox),
    [inbox, selectedId],
  )

  async function onStart(event: FormEvent) {
    event.preventDefault()
    const id = newTaskId.trim()
    if (!id) {
      setError("Give this isolated coding task an id.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const created = await startCodingTask({
        task_id: id,
        repo: repo.trim() || undefined,
      })
      setNewTaskId("")
      setRepo("")
      setMsg(
        `Isolated worktree ready for ${created.task_id} on ${created.branch}. Jarvis will not write to the primary checkout.`,
      )
      await refreshList()
      navigate(`/coding/${encodeURIComponent(created.task_id)}`)
    } catch (err: unknown) {
      setError(formatCodingError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onComplete() {
    if (!selectedId) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const tests: Record<string, unknown> = {}
      if (testsPassed || testsNotes.trim()) {
        tests.passed = testsPassed
        if (testsNotes.trim()) tests.notes = testsNotes.trim()
      }
      const result: CodingCompleteResult = await completeCodingTask(
        selectedId,
        Object.keys(tests).length ? tests : undefined,
      )
      setDetail(result.task)
      const conflicts = result.conflicts || []
      if (conflicts.length) {
        setMsg(
          `Recorded ${result.task.task_id}. ${conflicts.length} conflict${conflicts.length === 1 ? "" : "s"} went to Decision Inbox — Jarvis did not auto-resolve them.`,
        )
      } else {
        setMsg(`Recorded ${result.task.task_id}. Base SHA, branch, worktree, commits, tests, and diff are on file. Nothing was merged.`)
      }
      await Promise.all([refreshList(), refreshInbox()])
    } catch (err: unknown) {
      setError(formatCodingError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onApprove() {
    if (!selectedId) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const updated = await approveCodingTask(selectedId, approver.trim() || "human")
      setDetail(updated)
      setMsg(
        `${updated.task_id} is approved by ${updated.approved_by || "human"}. Integrate still does not merge into the trusted branch.`,
      )
      await refreshList()
    } catch (err: unknown) {
      setError(formatCodingError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onIntegrate() {
    if (!selectedId) return
    const ok = window.confirm(INTEGRATE_CONFIRM)
    if (!ok) return
    setBusy(true)
    setError("")
    setMsg("")
    setIntegrateResult(null)
    try {
      const result = await integrateCodingTask(selectedId)
      setIntegrateResult(result)
      if (codingIntegrationBlocked(result)) {
        const conflictCount = result.conflicts?.length || 0
        const extra = conflictCount
          ? ` ${conflictCount} conflict${conflictCount === 1 ? "" : "s"} are in Decision Inbox.`
          : ""
        setError(
          (result.message || "Integrate is blocked until a verifier or you approve.") + extra,
        )
      } else {
        setMsg(
          result.message ||
            "Candidate branch is ready for a human merge. The trusted branch was not changed. Nothing landed silently.",
        )
      }
      await Promise.all([refreshList(), refreshInbox(), refreshDetail(selectedId).catch(() => undefined)])
    } catch (err: unknown) {
      setError(formatCodingError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onCleanup(task: CodingTaskRecord) {
    const ok = window.confirm(
      `Clean up “${task.task_id}”? ${CLEANUP_CONFIRM}`,
    )
    if (!ok) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const updated = await cleanupCodingTask(task.task_id)
      setMsg(`Worktree for ${updated.task_id} was removed. The primary checkout was not modified.`)
      await refreshList()
      if (selectedId === task.task_id) {
        setDetail(updated)
      }
    } catch (err: unknown) {
      setError(formatCodingError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onResolve(item: CodingDecisionInboxItem) {
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const resolved = await resolveCodingDecisionInboxItem(
        item.id,
        (resolutionDrafts[item.id] || "").trim(),
      )
      setMsg(`Decision ${resolved.id} marked resolved. Jarvis did not auto-merge anything.`)
      setResolutionDrafts((current) => {
        const next = { ...current }
        delete next[item.id]
        return next
      })
      await refreshInbox()
    } catch (err: unknown) {
      setError(formatCodingError(err))
    } finally {
      setBusy(false)
    }
  }

  const workerCount = overview?.workers?.length || 0

  return (
    <div className="coding-page">
      <h1>Coding isolation</h1>
      <p className="lede">
        Every coding task gets its own Git worktree and branch. Jarvis never writes to the primary
        checkout. <strong>Nothing lands silently</strong> — integrate is blocked until a verifier or
        you approve. Overlaps go to Decision Inbox and are never auto-resolved.
      </p>

      {error && (
        <div className="card coding-banner bad" role="alert">
          {error}
        </div>
      )}
      {msg && (
        <div className="card coding-banner warn">
          {msg}
        </div>
      )}

      {selectedId && selected ? (
        <TaskDetail
          task={selected}
          inbox={selectedInbox}
          busy={busy}
          approver={approver}
          testsPassed={testsPassed}
          testsNotes={testsNotes}
          integrateResult={integrateResult}
          resolutionDrafts={resolutionDrafts}
          onApprover={setApprover}
          onTestsPassed={setTestsPassed}
          onTestsNotes={setTestsNotes}
          onComplete={onComplete}
          onApprove={onApprove}
          onIntegrate={onIntegrate}
          onCleanup={() => onCleanup(selected)}
          onResolve={onResolve}
          onResolution={(id, value) =>
            setResolutionDrafts((current) => ({ ...current, [id]: value }))
          }
        />
      ) : selectedId && !selected ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <p className="lede" style={{ margin: 0 }}>
            This coding task could not be opened.{" "}
            <Link to="/coding">Back to isolated worktrees</Link>
          </p>
        </div>
      ) : (
        <>
          <div className="card coding-callout">
            <p className="license-kicker">No silent merge</p>
            <p className="lede" style={{ margin: 0 }}>
              Approve, then integrate. Integrate still does not merge into the trusted branch — it
              only marks a candidate for a human merge. Conflicts stay in Decision Inbox until you
              resolve them. {workerCount ? `${workerCount} software workers are listed on Tools.` : ""}
            </p>
          </div>

          <form className="card grid" style={{ maxWidth: 760, marginBottom: 16 }} onSubmit={onStart}>
            <h2>Isolate a coding task</h2>
            <p className="lede" style={{ margin: "0 0 12px" }}>
              Creates a dedicated worktree and <code>jarvis/coding-task-…</code> branch. Uncommitted
              work in the primary checkout is left alone.
            </p>
            <label>
              Task id
              <input
                type="text"
                value={newTaskId}
                onChange={(event) => setNewTaskId(event.target.value)}
                placeholder="fix-login"
                aria-label="Coding task id"
              />
            </label>
            <label>
              Repository path (optional)
              <input
                type="text"
                value={repo}
                onChange={(event) => setRepo(event.target.value)}
                placeholder="Leave blank for this Jarvis repo"
                aria-label="Repository path"
              />
            </label>
            <div className="row">
              <button className="btn" type="submit" disabled={busy}>
                Create isolated worktree
              </button>
            </div>
          </form>

          <DecisionInboxPanel
            items={inbox}
            openOnly={openOnly}
            scoped={false}
            busy={busy}
            drafts={resolutionDrafts}
            onOpenOnly={setOpenOnly}
            onDraft={(id, value) => setResolutionDrafts((current) => ({ ...current, [id]: value }))}
            onResolve={onResolve}
          />
        </>
      )}

      <div className="card">
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>{selectedId ? "All isolated worktrees" : "Isolated worktrees"}</span>
          <label className="row" style={{ gap: 8, color: "var(--muted)", fontSize: 13 }}>
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(event) => setActiveOnly(event.target.checked)}
            />
            Active only
          </label>
        </div>
        {selectedId && (
          <p className="lede" style={{ margin: "0 0 12px" }}>
            <Link to="/coding">New isolated task</Link>
          </p>
        )}
        {tasks.length === 0 ? (
          <p className="lede" style={{ margin: 0 }}>
            No isolated coding tasks yet. Create one so a worker cannot share a checkout with another
            task or with you.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>Status</th>
                <th>Branch</th>
                <th>Base SHA</th>
                <th>Worktree</th>
                <th>Integration</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr
                  key={task.task_id}
                  className={`env-row${task.task_id === selectedId ? " selected" : ""}`}
                  onClick={() => navigate(`/coding/${encodeURIComponent(task.task_id)}`)}
                >
                  <td>
                    <strong>{task.task_id}</strong>
                    {task.cleaned_up ? (
                      <div className="lede" style={{ margin: "4px 0 0" }}>Worktree removed</div>
                    ) : null}
                  </td>
                  <td>
                    <span className={`badge ${taskStatusClass(task.status)}`}>
                      {taskStatusLabel(task.status)}
                    </span>
                  </td>
                  <td title={task.branch}>{task.branch || "—"}</td>
                  <td title={task.base_sha}>{shortSha(task.base_sha)}</td>
                  <td title={task.worktree_path}>
                    <code className="coding-path">{task.worktree_path || "—"}</code>
                  </td>
                  <td>
                    <span className={`badge ${integrationClass(task.integration_status, task.verifier_approved)}`}>
                      {integrationLabel(task.integration_status, task.verifier_approved)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function TaskDetail({
  task,
  inbox,
  busy,
  approver,
  testsPassed,
  testsNotes,
  integrateResult,
  resolutionDrafts,
  onApprover,
  onTestsPassed,
  onTestsNotes,
  onComplete,
  onApprove,
  onIntegrate,
  onCleanup,
  onResolve,
  onResolution,
}: {
  task: CodingTaskRecord
  inbox: CodingDecisionInboxItem[]
  busy: boolean
  approver: string
  testsPassed: boolean
  testsNotes: string
  integrateResult: CodingIntegrateResult | null
  resolutionDrafts: Record<string, string>
  onApprover: (value: string) => void
  onTestsPassed: (value: boolean) => void
  onTestsNotes: (value: string) => void
  onComplete: () => void
  onApprove: () => void
  onIntegrate: () => void
  onCleanup: () => void
  onResolve: (item: CodingDecisionInboxItem) => void
  onResolution: (id: string, value: string) => void
}) {
  const openConflicts = inbox.filter((item) => item.status === "open")
  const canAct = !task.cleaned_up
  const approved = Boolean(task.verifier_approved)

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="rail-heading" style={{ padding: "0 0 8px" }}>
        <span>Isolated task</span>
        <Link className="btn secondary" to="/coding">
          All worktrees
        </Link>
      </div>
      <h2 style={{ marginBottom: 8 }}>{task.task_id}</h2>
      <p className="lede">
        This worker may only write inside its worktree. Approve, then integrate — integrate still
        does not merge. {openConflicts.length
          ? `${openConflicts.length} open Decision Inbox item${openConflicts.length === 1 ? "" : "s"} must be resolved before approval.`
          : "No open conflicts for this task."}
      </p>

      <div className="kv">
        <b>Status</b>
        <span className={`badge ${taskStatusClass(task.status)}`}>{taskStatusLabel(task.status)}</span>
        <b>Base SHA</b>
        <span title={task.base_sha}>{task.base_sha || "—"}</span>
        <b>Branch</b>
        <span>{task.branch || "—"}</span>
        <b>Worktree path</b>
        <span><code className="coding-path">{task.worktree_path || "—"}</code></span>
        <b>Worktree id</b>
        <span>{task.worktree_id || "—"}</span>
        <b>Integration</b>
        <span className={`badge ${integrationClass(task.integration_status, approved)}`}>
          {integrationLabel(task.integration_status, approved)}
        </span>
        <b>Verifier / human</b>
        <span>
          {approved
            ? `Approved by ${task.approved_by || "unknown"} (${formatWhen(task.approved_at)})`
            : "Not approved — integrate will no-op"}
        </span>
        <b>Created</b>
        <span>{formatWhen(task.created_at)}</span>
        <b>Recorded</b>
        <span>{formatWhen(task.completed_at)}</span>
        <b>Cleaned up</b>
        <span>{task.cleaned_up ? "Yes — worktree removed" : "No"}</span>
      </div>

      <h3 className="env-subhead">Commits</h3>
      {task.commits?.length ? (
        <ul className="env-file-list">
          {task.commits.map((commit) => (
            <li key={commit} title={commit}>
              <code>{commit}</code>
            </li>
          ))}
        </ul>
      ) : (
        <p className="lede" style={{ margin: 0 }}>No commits recorded on this isolated branch yet.</p>
      )}

      <h3 className="env-subhead">Tests</h3>
      <p className="lede" style={{ margin: 0 }}>{testsSummary(task.tests)}</p>
      {task.tests && Object.keys(task.tests).length > 0 && (
        <pre className="env-json">{prettyJson(task.tests)}</pre>
      )}

      <h3 className="env-subhead">Final diff</h3>
      {hasDiff(task.final_diff) ? (
        <div>
          <div className="kv" style={{ marginBottom: 8 }}>
            <b>Diff base</b>
            <span title={task.final_diff.base}>{task.final_diff.base || "—"}</span>
            <b>Head</b>
            <span title={task.final_diff.head}>{task.final_diff.head || "—"}</span>
          </div>
          {task.final_diff.stat ? <pre className="env-json">{task.final_diff.stat}</pre> : null}
          {task.final_diff.files ? (
            <>
              <h3 className="env-subhead">Files</h3>
              <pre className="env-json">{task.final_diff.files}</pre>
            </>
          ) : null}
        </div>
      ) : (
        <p className="lede" style={{ margin: 0 }}>
          No final diff yet. Record the task to capture the diff against the base SHA.
        </p>
      )}

      {integrateResult && (
        <div
          className={`card coding-integrate-result${codingIntegrationBlocked(integrateResult) ? " blocked" : ""}`}
        >
          <p className="license-kicker">
            {codingIntegrationBlocked(integrateResult) ? "Integrate blocked" : "Candidate only"}
          </p>
          <p className="lede" style={{ margin: 0 }}>
            {integrateResult.message ||
              (codingIntegrationBlocked(integrateResult)
                ? "Verifier or human approval is required. Nothing was merged."
                : "Trusted branch was not changed.")}
          </p>
          {integrateResult.conflicts?.length ? (
            <ul className="env-file-list">
              {integrateResult.conflicts.map((item) => (
                <li key={item.id}>
                  {item.title}: {item.detail}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}

      {canAct && (
        <>
          <h3 className="env-subhead">Record result</h3>
          <label className="row" style={{ marginBottom: 8 }}>
            <input
              type="checkbox"
              checked={testsPassed}
              onChange={(event) => onTestsPassed(event.target.checked)}
            />
            Tests recorded as passed
          </label>
          <label>
            Test notes (optional)
            <textarea
              className="field"
              rows={3}
              value={testsNotes}
              onChange={(event) => onTestsNotes(event.target.value)}
              placeholder="pytest, lint, what was checked"
              aria-label="Test notes"
            />
          </label>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn secondary" type="button" disabled={busy} onClick={onComplete}>
              Record task
            </button>
          </div>

          <h3 className="env-subhead">Approve, then integrate</h3>
          <p className="lede">
            Integrate is a no-op until this is approved. Even after approval, Jarvis does not merge
            into the trusted branch.
          </p>
          <label>
            Approver
            <input
              type="text"
              value={approver}
              onChange={(event) => onApprover(event.target.value)}
              placeholder="human"
              aria-label="Approver"
            />
          </label>
          <div className="row coding-actions" style={{ marginTop: 12 }}>
            <button className="btn" type="button" disabled={busy} onClick={onApprove}>
              Approve
            </button>
            <button
              className="btn secondary"
              type="button"
              disabled={busy}
              title="Blocked without approval. Never a silent merge."
              onClick={onIntegrate}
            >
              Integrate
            </button>
            <button className="btn danger" type="button" disabled={busy} onClick={onCleanup}>
              Clean up worktree
            </button>
          </div>
        </>
      )}

      {task.cleaned_up && (
        <p className="lede" style={{ margin: "16px 0 0" }}>
          This worktree is gone. Isolation fields above stay on file for review.
        </p>
      )}

      {inbox.length > 0 && (
        <>
          <h3 className="env-subhead">Decisions for this task</h3>
          {inbox.map((item) => (
            <InboxCard
              key={item.id}
              item={item}
              busy={busy}
              draft={resolutionDrafts[item.id] || ""}
              onDraft={(value) => onResolution(item.id, value)}
              onResolve={() => onResolve(item)}
            />
          ))}
        </>
      )}
    </div>
  )
}

function DecisionInboxPanel({
  items,
  openOnly,
  scoped,
  busy,
  drafts,
  onOpenOnly,
  onDraft,
  onResolve,
}: {
  items: CodingDecisionInboxItem[]
  openOnly: boolean
  scoped: boolean
  busy: boolean
  drafts: Record<string, string>
  onOpenOnly: (value: boolean) => void
  onDraft: (id: string, value: string) => void
  onResolve: (item: CodingDecisionInboxItem) => void
}) {
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="rail-heading" style={{ padding: "0 0 8px" }}>
        <span>Decision Inbox</span>
        <label className="row" style={{ gap: 8, color: "var(--muted)", fontSize: 13 }}>
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(event) => onOpenOnly(event.target.checked)}
          />
          Open only
        </label>
      </div>
      <p className="lede">
        Overlapping files between parallel coding tasks land here. Jarvis never auto-resolves them
        and never merges while an item is open.
        {scoped ? " Showing items tied to this task." : ""}
      </p>
      {items.length === 0 ? (
        <p className="lede" style={{ margin: 0 }}>
          {openOnly ? "No open decisions." : "No decisions recorded."}
        </p>
      ) : (
        items.map((item) => (
          <InboxCard
            key={item.id}
            item={item}
            busy={busy}
            draft={drafts[item.id] || ""}
            onDraft={(value) => onDraft(item.id, value)}
            onResolve={() => onResolve(item)}
          />
        ))
      )}
    </div>
  )
}

function InboxCard({
  item,
  busy,
  draft,
  onDraft,
  onResolve,
}: {
  item: CodingDecisionInboxItem
  busy: boolean
  draft: string
  onDraft: (value: string) => void
  onResolve: () => void
}) {
  return (
    <div className={`context-entry${item.status === "open" ? " conflict" : ""}`}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{item.title || kindLabel(item.kind)}</strong>
        <span className={`badge ${inboxStatusClass(item.status)}`}>{item.status || "open"}</span>
      </div>
      <p className="lede" style={{ margin: "6px 0 8px" }}>{item.detail || "No detail."}</p>
      <div className="kv">
        <b>Kind</b>
        <span>{kindLabel(item.kind)}</span>
        <b>Task</b>
        <span>
          {item.task_id ? (
            <Link to={`/coding/${encodeURIComponent(item.task_id)}`}>{item.task_id}</Link>
          ) : (
            "—"
          )}
        </span>
        <b>Related</b>
        <span>
          {item.related_task_id ? (
            <Link to={`/coding/${encodeURIComponent(item.related_task_id)}`}>{item.related_task_id}</Link>
          ) : (
            "—"
          )}
        </span>
        <b>Opened</b>
        <span>{formatWhen(item.created_at)}</span>
        {item.status !== "open" && (
          <>
            <b>Resolved</b>
            <span>{formatWhen(item.resolved_at)}</span>
            <b>Resolution</b>
            <span>{item.resolution || "—"}</span>
          </>
        )}
      </div>
      {item.status === "open" && (
        <div style={{ marginTop: 10 }}>
          <label>
            How this was resolved
            <input
              type="text"
              value={draft}
              onChange={(event) => onDraft(event.target.value)}
              placeholder="Keep task A’s file; rebase task B"
              aria-label={`Resolution for ${item.title || item.id}`}
            />
          </label>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn secondary" type="button" disabled={busy} onClick={onResolve}>
              Resolve
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
