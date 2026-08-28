import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  allowedDelegationAutonomy,
  allowedDelegationPrivacy,
  authorityFromTask,
  authorityFromWorker,
  completeDelegatedWorker,
  failDelegatedWorker,
  formatDelegationError,
  listDelegationEvents,
  listDelegationGraph,
  spawnDelegatedChild,
  startDelegatedWorker,
  type DelegationAuthority,
  type DelegatedWorker,
  type DelegationEvent,
  type Task,
  api,
} from "../api"

const AUTONOMY_COPY: Record<string, string> = {
  interactive: "Ask first",
  trusted: "Trusted",
  autonomous: "Act on its own",
}

const PRIVACY_COPY: Record<string, string> = {
  public: "Open",
  internal: "Internal",
  confidential: "Confidential",
  restricted: "Restricted",
}

const STATUS_COPY: Record<string, string> = {
  pending: "Waiting",
  running: "Working",
  completed: "Done",
  failed: "Failed",
  expired: "Timed out",
}

const EVENT_COPY: Record<string, string> = {
  spawned: "Helper added",
  status: "Status change",
  result: "Helper finished",
  failure: "Helper failed",
  expired: "Helper timed out",
}

const ACTIVE_HELPER = new Set(["pending", "running"])

function statusClass(status: string): string {
  const key = status.toLowerCase()
  if (key === "completed") return "completed"
  if (key === "running") return "running"
  if (key === "failed") return "failed"
  if (key === "expired") return "expired"
  return "pending"
}

function statusLabel(status: string): string {
  return STATUS_COPY[status.toLowerCase()] || status
}

function autonomyLabel(value: string): string {
  return AUTONOMY_COPY[value.toLowerCase()] || value
}

function privacyLabel(value: string): string {
  return PRIVACY_COPY[value.toLowerCase()] || value
}

function eventLabel(kind: string): string {
  return EVENT_COPY[kind.toLowerCase()] || kind.replaceAll("_", " ")
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function taskLabel(task: Task): string {
  return task.title || task.prompt?.slice(0, 72) || "Untitled task"
}

function helperLabel(worker: DelegatedWorker): string {
  const text = (worker.task || "").trim()
  if (!text) return "Helper"
  return text.length > 72 ? `${text.slice(0, 72)}…` : text
}

function childrenOf(workers: DelegatedWorker[], parentId: string | null): DelegatedWorker[] {
  return workers.filter((worker) => (worker.parent_worker_id || null) === parentId)
}

function toIsoDeadline(localValue: string): string | null {
  const trimmed = localValue.trim()
  if (!trimmed) return null
  const parsed = new Date(trimmed)
  if (Number.isNaN(parsed.getTime())) return trimmed
  return parsed.toISOString()
}

function parseOptionalInt(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed)) return null
  return Math.max(1, Math.round(parsed))
}

type SpawnFormState = {
  parentWorkerId: string
  task: string
  tools: string[]
  autonomy: string
  privacy: string
  contextKeys: string[]
  budget: Record<string, string>
  ttl: string
  deadline: string
}

function emptySpawn(authority: DelegationAuthority, parentWorkerId = ""): SpawnFormState {
  return {
    parentWorkerId,
    task: "",
    tools: [],
    autonomy: authority.autonomy,
    privacy: authority.privacy_class,
    contextKeys: [],
    budget: Object.fromEntries(Object.keys(authority.budget).map((key) => [key, String(authority.budget[key])])),
    ttl: "",
    deadline: "",
  }
}

export function DelegationPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<Task[]>([])
  const [task, setTask] = useState<Task | null>(null)
  const [loadError, setLoadError] = useState("")

  useEffect(() => {
    api<Task[]>("/api/tasks")
      .then(setTasks)
      .catch((err: unknown) => setLoadError(formatDelegationError(err)))
  }, [])

  useEffect(() => {
    if (!taskId) {
      setTask(null)
      return
    }
    let cancelled = false
    const load = async () => {
      try {
        const data = await api<Task>(`/api/tasks/${taskId}`)
        if (!cancelled) {
          setTask(data)
          setLoadError("")
        }
      } catch (err: unknown) {
        if (!cancelled) setLoadError(formatDelegationError(err))
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), 8000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [taskId])

  return (
    <div className="delegation-page">
      <h1>Helpers</h1>
      <p className="lede">
        Short-lived helpers can take a bounded slice of a task. They cannot get extra tools, extra
        freedom, or looser privacy than the parent. The parent task stays responsible.
      </p>
      {loadError && (
        <div className="card delegation-banner bad" role="status">
          {loadError}
        </div>
      )}
      <div className="card" style={{ maxWidth: 720, marginBottom: 16 }}>
        <label>
          Parent task
          <select
            value={taskId || ""}
            onChange={(event) => {
              const value = event.target.value
              if (value) navigate(`/delegation/${value}`)
              else navigate("/delegation")
            }}
          >
            <option value="">Choose a task</option>
            {tasks.map((item) => (
              <option key={item.id} value={item.id}>
                {taskLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <p className="lede" style={{ margin: "10px 0 0" }}>
          Helpers are listed per parent task. There is no separate list of every helper on this PC.
        </p>
      </div>
      {taskId && task && <DelegationPanel key={taskId} parentTaskId={taskId} task={task} />}
      {taskId && !task && !loadError && <p className="lede">Opening task…</p>}
      {!taskId && tasks.length === 0 && <p className="lede">No tasks yet. Start one from New task, then come back here.</p>}
    </div>
  )
}

export function DelegationPanel({
  parentTaskId,
  task,
  compact = false,
}: {
  parentTaskId: string
  task: Task
  compact?: boolean
}) {
  const [workers, setWorkers] = useState<DelegatedWorker[]>([])
  const [events, setEvents] = useState<DelegationEvent[]>([])
  const [graphError, setGraphError] = useState("")
  const [actionError, setActionError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [spawnOpen, setSpawnOpen] = useState(!compact)
  const [failReason, setFailReason] = useState("")

  const taskAuthority = useMemo(() => authorityFromTask(task), [task])
  const selected = workers.find((worker) => worker.id === selectedId) || null

  const load = useCallback(async () => {
    try {
      const [graph, timeline] = await Promise.all([
        listDelegationGraph(parentTaskId),
        listDelegationEvents(parentTaskId),
      ])
      setWorkers(graph)
      setEvents(timeline)
      setGraphError("")
    } catch (err: unknown) {
      setGraphError(formatDelegationError(err))
    }
  }, [parentTaskId])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 4000)
    return () => window.clearInterval(timer)
  }, [load])

  const [form, setForm] = useState<SpawnFormState>(() => emptySpawn(taskAuthority))

  const spawnParentWorker = form.parentWorkerId
    ? workers.find((item) => item.id === form.parentWorkerId) || null
    : null
  const spawnAuthority =
    spawnParentWorker && ACTIVE_HELPER.has(spawnParentWorker.status.toLowerCase())
      ? authorityFromWorker(spawnParentWorker)
      : taskAuthority

  useEffect(() => {
    if (!form.parentWorkerId) return
    const parent = workers.find((item) => item.id === form.parentWorkerId)
    if (!parent || !ACTIVE_HELPER.has(parent.status.toLowerCase())) {
      setForm(emptySpawn(taskAuthority, ""))
    }
  }, [workers, form.parentWorkerId, taskAuthority])

  const autonomyOptions = allowedDelegationAutonomy(spawnAuthority.autonomy)
  const privacyOptions = allowedDelegationPrivacy(spawnAuthority.privacy_class)
  const contextKeys = Object.keys(spawnAuthority.context)
  const budgetKeys = Object.keys(spawnAuthority.budget)
  const roots = childrenOf(workers, null)

  async function onSpawn(event: FormEvent) {
    event.preventDefault()
    const taskText = form.task.trim()
    if (!taskText) {
      setActionError("Describe what the helper should do.")
      return
    }
    if (!autonomyOptions.includes(form.autonomy as (typeof autonomyOptions)[number])) {
      setActionError("A helper cannot have more freedom than its parent.")
      return
    }
    if (!privacyOptions.includes(form.privacy as (typeof privacyOptions)[number])) {
      setActionError("A helper cannot have looser privacy than its parent.")
      return
    }
    const context: Record<string, unknown> = {}
    for (const key of form.contextKeys) {
      if (Object.prototype.hasOwnProperty.call(spawnAuthority.context, key)) {
        context[key] = spawnAuthority.context[key]
      }
    }
    const budget: Record<string, unknown> = {}
    for (const key of budgetKeys) {
      const parsed = Number(form.budget[key])
      if (Number.isFinite(parsed)) budget[key] = parsed
    }
    setBusy(true)
    setActionError("")
    setNotice("")
    try {
      const created = await spawnDelegatedChild(
        parentTaskId,
        {
          task: taskText,
          parent_worker_id: form.parentWorkerId || null,
          tools: form.tools,
          autonomy: form.autonomy,
          privacy_class: form.privacy,
          context,
          budget,
          ttl_seconds: parseOptionalInt(form.ttl),
          deadline_at: toIsoDeadline(form.deadline),
        },
        spawnAuthority,
      )
      setSelectedId(created.id)
      setNotice("Helper added. It cannot exceed the parent’s tools, freedom, or privacy.")
      setForm(emptySpawn(spawnAuthority, form.parentWorkerId))
      await load()
    } catch (err: unknown) {
      setActionError(formatDelegationError(err))
    } finally {
      setBusy(false)
    }
  }

  async function runAction(action: () => Promise<unknown>, ok: string) {
    setBusy(true)
    setActionError("")
    setNotice("")
    try {
      await action()
      setNotice(ok)
      await load()
    } catch (err: unknown) {
      setActionError(formatDelegationError(err))
    } finally {
      setBusy(false)
    }
  }

  function toggleTool(name: string) {
    const key = name.toLowerCase()
    if (!spawnAuthority.tools.some((item) => item.toLowerCase() === key)) return
    setForm((prev) => {
      const has = prev.tools.some((item) => item.toLowerCase() === key)
      return {
        ...prev,
        tools: has ? prev.tools.filter((item) => item.toLowerCase() !== key) : [...prev.tools, key],
      }
    })
  }

  function toggleContext(key: string) {
    if (!Object.prototype.hasOwnProperty.call(spawnAuthority.context, key)) return
    setForm((prev) => ({
      ...prev,
      contextKeys: prev.contextKeys.includes(key)
        ? prev.contextKeys.filter((item) => item !== key)
        : [...prev.contextKeys, key],
    }))
  }

  function chooseParent(parentWorkerId: string) {
    const parent = parentWorkerId ? workers.find((item) => item.id === parentWorkerId) : null
    if (parent && !ACTIVE_HELPER.has(parent.status.toLowerCase())) return
    const nextAuthority = parent ? authorityFromWorker(parent) : taskAuthority
    setForm(emptySpawn(nextAuthority, parentWorkerId))
    if (parent) setSelectedId(parent.id)
  }

  return (
    <div className={`delegation-panel${compact ? " compact" : ""}`}>
      <div className="delegation-cap-note" role="note">
        Helpers cannot get extra tools, extra freedom, or looser privacy than the parent. The parent
        task stays accountable.
      </div>
      {graphError && (
        <div className="card delegation-banner bad" role="alert">
          {graphError}
        </div>
      )}
      {actionError && (
        <div className="card delegation-banner bad" role="alert">
          {actionError}
        </div>
      )}
      {notice && (
        <div className="card delegation-banner ok" role="status">
          {notice}
        </div>
      )}

      <div className={`delegation-layout${compact ? "" : " two"}`}>
        <div className="card">
          <h2>Family</h2>
          <p className="lede" style={{ marginBottom: 12 }}>
            Parent on top. Each helper sits under the parent it was given work by.
          </p>
          <ul className="delegation-tree">
            <li>
              <div className={`delegation-node root${selectedId ? "" : " selected"}`}>
                <span className={`badge ${statusClass(task.status)}`}>{statusLabel(task.status)}</span>
                <strong>{taskLabel(task)}</strong>
                <span className="delegation-node-meta">Parent · stays responsible</span>
              </div>
              {roots.length === 0 && <p className="rail-empty">No helpers yet for this task.</p>}
              {roots.length > 0 && (
                <ul>
                  {roots.map((worker) => (
                    <TreeNode
                      key={worker.id}
                      worker={worker}
                      workers={workers}
                      selectedId={selectedId}
                      onSelect={setSelectedId}
                    />
                  ))}
                </ul>
              )}
            </li>
          </ul>
        </div>

        <div className="card">
          <h2>Activity</h2>
          <p className="lede" style={{ marginBottom: 12 }}>
            What helpers did on this parent task.
          </p>
          {events.length === 0 && <p className="lede">No helper activity yet.</p>}
          <div className="timeline">
            {events.map((event) => {
              const owner = workers.find((item) => item.id === event.worker_id)
              return (
                <div className="t-item" key={String(event.id)}>
                  <div className="rail" />
                  <div>
                    <strong>{eventLabel(event.kind)}</strong>
                    <p>
                      {event.title}
                      {owner ? ` · ${helperLabel(owner)}` : ""}
                      {event.created_at ? ` · ${formatWhen(event.created_at)}` : ""}
                    </p>
                    {event.detail && <p>{event.detail.slice(0, 400)}</p>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {selected && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Selected helper</h2>
          <div className="kv" style={{ marginTop: 8 }}>
            <b>Work</b>
            <span>{selected.task}</span>
            <b>Status</b>
            <span className={`badge ${statusClass(selected.status)}`}>{statusLabel(selected.status)}</span>
            <b>Freedom</b>
            <span>{autonomyLabel(selected.autonomy)} — cannot exceed parent</span>
            <b>Privacy</b>
            <span>{privacyLabel(selected.privacy_class)} — same or tighter than parent</span>
            <b>Tools</b>
            <span>{selected.tools.length ? selected.tools.join(", ") : "None"}</span>
            <b>Depth</b>
            <span>{selected.depth}</span>
            {selected.deadline_at && (
              <>
                <b>Deadline</b>
                <span>{formatWhen(selected.deadline_at)}</span>
              </>
            )}
            {selected.expires_at && (
              <>
                <b>Expires</b>
                <span>{formatWhen(selected.expires_at)}</span>
              </>
            )}
            {selected.error && (
              <>
                <b>Issue</b>
                <span>{selected.error}</span>
              </>
            )}
            {selected.result && Object.keys(selected.result).length > 0 && (
              <>
                <b>Result</b>
                <span className="stat">{JSON.stringify(selected.result)}</span>
              </>
            )}
          </div>
          {ACTIVE_HELPER.has(selected.status.toLowerCase()) && (
            <div className="row" style={{ marginTop: 12 }}>
              {selected.status === "pending" && (
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={() => runAction(() => startDelegatedWorker(selected.id), "Helper is working.")}
                >
                  Start
                </button>
              )}
              <button
                className="btn secondary"
                type="button"
                disabled={busy}
                onClick={() => runAction(() => completeDelegatedWorker(selected.id, { ok: true }), "Helper marked done.")}
              >
                Mark done
              </button>
              <input
                type="text"
                placeholder="If it failed, say why"
                value={failReason}
                onChange={(event) => setFailReason(event.target.value)}
                style={{ maxWidth: 280 }}
              />
              <button
                className="btn secondary"
                type="button"
                disabled={busy || !failReason.trim()}
                onClick={() =>
                  runAction(() => failDelegatedWorker(selected.id, failReason.trim()), "Helper marked failed.")
                }
              >
                Mark failed
              </button>
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <div className="rail-heading" style={{ padding: 0, textTransform: "none", letterSpacing: 0 }}>
          <h2 style={{ margin: 0 }}>Add a helper</h2>
          {compact && (
            <button className="btn secondary" type="button" onClick={() => setSpawnOpen((open) => !open)}>
              {spawnOpen ? "Hide" : "Show"}
            </button>
          )}
        </div>
        {spawnOpen && (
          <form className="delegation-spawn" onSubmit={onSpawn}>
            <p className="lede">
              Only tools, freedom, and privacy the parent already has. Nothing above that ceiling.
            </p>
            <label>
              Add under
              <select
                value={form.parentWorkerId}
                onChange={(event) => chooseParent(event.target.value)}
              >
                <option value="">Parent task — {taskLabel(task)}</option>
                {workers
                  .filter((worker) => ACTIVE_HELPER.has(worker.status.toLowerCase()))
                  .map((worker) => (
                    <option key={worker.id} value={worker.id}>
                      Helper · {helperLabel(worker)} ({statusLabel(worker.status)})
                    </option>
                  ))}
              </select>
            </label>
            <label>
              What should this helper do?
              <textarea
                className="field"
                rows={3}
                value={form.task}
                onChange={(event) => setForm((prev) => ({ ...prev, task: event.target.value }))}
                placeholder="A bounded slice of the parent task"
              />
            </label>
            <fieldset className="axis-fieldset">
              <legend>Tools this helper may use</legend>
              <p>Only the parent’s tools are listed. Extra tools are not offered. None are selected until you pick them.</p>
              {spawnAuthority.tools.length === 0 && (
                <p className="lede" style={{ margin: 0 }}>This parent has no tools to share.</p>
              )}
              <div className="chip-row">
                {spawnAuthority.tools.map((tool) => {
                  const on = form.tools.some((item) => item.toLowerCase() === tool.toLowerCase())
                  return (
                    <button
                      key={tool}
                      type="button"
                      className={`chip${on ? " on" : ""}`}
                      onClick={() => toggleTool(tool)}
                    >
                      {tool}
                    </button>
                  )
                })}
              </div>
            </fieldset>
            <label>
              Freedom (cannot exceed {autonomyLabel(spawnAuthority.autonomy)})
              <select
                value={form.autonomy}
                onChange={(event) => {
                  const value = event.target.value
                  if (!autonomyOptions.includes(value as (typeof autonomyOptions)[number])) return
                  setForm((prev) => ({ ...prev, autonomy: value }))
                }}
              >
                {autonomyOptions.map((item) => (
                  <option key={item} value={item}>
                    {autonomyLabel(item)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Privacy (cannot be looser than {privacyLabel(spawnAuthority.privacy_class)})
              <select
                value={form.privacy}
                onChange={(event) => {
                  const value = event.target.value
                  if (!privacyOptions.includes(value as (typeof privacyOptions)[number])) return
                  setForm((prev) => ({ ...prev, privacy: value }))
                }}
              >
                {privacyOptions.map((item) => (
                  <option key={item} value={item}>
                    {privacyLabel(item)}
                  </option>
                ))}
              </select>
            </label>
            {contextKeys.length > 0 && (
              <fieldset className="axis-fieldset">
                <legend>Details the helper may see</legend>
                <p>Only details the parent already has. New secrets cannot be added here.</p>
                <div className="chip-row">
                  {contextKeys.map((key) => (
                    <button
                      key={key}
                      type="button"
                      className={`chip${form.contextKeys.includes(key) ? " on" : ""}`}
                      onClick={() => toggleContext(key)}
                    >
                      {key.replaceAll("_", " ")}
                    </button>
                  ))}
                </div>
              </fieldset>
            )}
            {budgetKeys.length > 0 && (
              <div className="delegation-budget">
                {budgetKeys.map((key) => (
                  <label key={key}>
                    {key.replaceAll("_", " ")} (max {spawnAuthority.budget[key]})
                    <input
                      type="number"
                      max={spawnAuthority.budget[key]}
                      value={form.budget[key] ?? ""}
                      onChange={(event) => {
                        const raw = event.target.value
                        const parsed = Number(raw)
                        const capped =
                          Number.isFinite(parsed) && parsed > spawnAuthority.budget[key]
                            ? String(spawnAuthority.budget[key])
                            : raw
                        setForm((prev) => ({ ...prev, budget: { ...prev.budget, [key]: capped } }))
                      }}
                    />
                  </label>
                ))}
              </div>
            )}
            <div className="delegation-budget">
              <label>
                Lifetime in seconds (optional)
                <input
                  type="number"
                  min={1}
                  value={form.ttl}
                  onChange={(event) => setForm((prev) => ({ ...prev, ttl: event.target.value }))}
                  placeholder="Uses the usual short limit if blank"
                />
              </label>
              <label>
                Deadline (optional)
                <input
                  type="datetime-local"
                  value={form.deadline}
                  onChange={(event) => setForm((prev) => ({ ...prev, deadline: event.target.value }))}
                />
              </label>
            </div>
            <div className="row">
              <button className="btn" type="submit" disabled={busy || !form.task.trim()}>
                Add helper
              </button>
              {compact && (
                <Link className="btn secondary" to={`/delegation/${parentTaskId}`}>
                  Open full view
                </Link>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

function TreeNode({
  worker,
  workers,
  selectedId,
  onSelect,
}: {
  worker: DelegatedWorker
  workers: DelegatedWorker[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const kids = childrenOf(workers, worker.id)
  return (
    <li>
      <button
        type="button"
        className={`delegation-node${selectedId === worker.id ? " selected" : ""}`}
        onClick={() => onSelect(worker.id)}
      >
        <span className={`badge ${statusClass(worker.status)}`}>{statusLabel(worker.status)}</span>
        <strong>{helperLabel(worker)}</strong>
        <span className="delegation-node-meta">
          {autonomyLabel(worker.autonomy)} · {privacyLabel(worker.privacy_class)}
          {worker.tools.length ? ` · ${worker.tools.length} tools` : " · no tools"}
        </span>
      </button>
      {kids.length > 0 && (
        <ul>
          {kids.map((child) => (
            <TreeNode
              key={child.id}
              worker={child}
              workers={workers}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  )
}
