import { Fragment, useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  createWorkerEnvironment,
  deleteWorkerEnvironment,
  getWorkerEnvironmentStatus,
  inspectWorkerEnvironment,
  listWorkerEnvironmentAudit,
  listWorkerEnvironments,
  resetWorkerEnvironment,
  resumeWorkerEnvironment,
  revokeWorkerEnvironmentCredential,
  startWorkerEnvironment,
  storeWorkerEnvironmentCredential,
  suspendWorkerEnvironment,
  type WorkerEnvironmentAuditEvent,
  type WorkerEnvironmentCredential,
  type WorkerEnvironmentInspect,
  type WorkerEnvironmentStatus,
} from "../api"

const KIND_OPTIONS = [
  { value: "general", label: "General" },
  { value: "browser", label: "Browser" },
  { value: "code", label: "Coding" },
] as const

const KIND_LABELS: Record<string, string> = {
  general: "General",
  browser: "Browser",
  code: "Coding",
}

const STATUS_LABELS: Record<string, string> = {
  created: "Not started",
  running: "Running",
  suspended: "Paused",
}

const EVENT_LABELS: Record<string, string> = {
  "environment.created": "Created",
  "environment.started": "Started",
  "environment.suspended": "Paused",
  "environment.resumed": "Resumed",
  "environment.reset": "Reset",
  "environment.deleted": "Removed",
  "credential.stored": "Key stored",
  "credential.revoked": "Key revoked",
}

const QUOTA_LABELS: Record<string, string> = {
  disk_mb: "Disk",
  cpu_threads: "CPU threads",
  ram_gb: "Memory",
  gpu_percent: "GPU",
  max_background_processes: "Background processes",
}

function statusBadgeClass(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === "running") return "running"
  if (normalized === "suspended") return "queued"
  if (normalized === "created") return "completed"
  return "queued"
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status
}

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] || kind || "—"
}

function eventLabel(event: string): string {
  return EVENT_LABELS[event] || event.replaceAll(".", " ")
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatDisk(env: Pick<WorkerEnvironmentStatus, "disk_usage_bytes" | "disk_usage_mb">): string {
  const bytes = Number(env.disk_usage_bytes) || 0
  const mb = Number(env.disk_usage_mb)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (Number.isFinite(mb) && mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`
  if (Number.isFinite(mb)) return `${mb < 10 ? mb.toFixed(2) : mb.toFixed(1)} MB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function diskLimitMb(env: WorkerEnvironmentStatus): number | null {
  const raw = (env.quotas as Record<string, unknown> | undefined)?.disk_mb
  const value = typeof raw === "number" ? raw : Number(raw)
  if (!Number.isFinite(value) || value <= 0) return null
  return value
}

function diskPercent(env: WorkerEnvironmentStatus): number | null {
  const limit = diskLimitMb(env)
  if (limit == null) return null
  const used = Number(env.disk_usage_mb) || 0
  return Math.max(0, Math.min(100, (used / limit) * 100))
}

function formatQuotaValue(key: string, value: unknown): string {
  const num = typeof value === "number" ? value : Number(value)
  if (!Number.isFinite(num)) return String(value ?? "—")
  if (key === "disk_mb") return `${num} MB`
  if (key === "ram_gb") return `${num} GB`
  if (key === "gpu_percent") return `${num}%`
  return String(num)
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message
  return fallback
}

function publicCredential(row: WorkerEnvironmentCredential): WorkerEnvironmentCredential {
  return {
    id: row.id,
    environment_id: row.environment_id,
    capability: row.capability,
    label: row.label,
    created_at: row.created_at,
    revoked_at: row.revoked_at ?? null,
  }
}

export function WorkerEnvironmentsPage() {
  const { environmentId } = useParams()
  const navigate = useNavigate()
  const [environments, setEnvironments] = useState<WorkerEnvironmentStatus[]>([])
  const [detail, setDetail] = useState<WorkerEnvironmentInspect | null>(null)
  const [status, setStatus] = useState<WorkerEnvironmentStatus | null>(null)
  const [audit, setAudit] = useState<WorkerEnvironmentAuditEvent[]>([])
  const [name, setName] = useState("")
  const [kind, setKind] = useState("general")
  const [agentProfile, setAgentProfile] = useState("default")
  const [diskLimit, setDiskLimit] = useState("")
  const [credCapability, setCredCapability] = useState("")
  const [credLabel, setCredLabel] = useState("")
  const [credSecret, setCredSecret] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  const refreshList = useCallback(async () => {
    const data = await listWorkerEnvironments()
    setEnvironments(data.environments || [])
  }, [])

  const refreshDetail = useCallback(async (id: string) => {
    const [inspected, live, events] = await Promise.all([
      inspectWorkerEnvironment(id),
      getWorkerEnvironmentStatus(id),
      listWorkerEnvironmentAudit({ environmentId: id, limit: 40 }).catch(() => ({ events: [] as WorkerEnvironmentAuditEvent[] })),
    ])
    setDetail({
      ...inspected,
      credentials: (inspected.credentials || []).map(publicCredential),
    })
    setStatus(live)
    setAudit(events.events || [])
  }, [])

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        await refreshList()
      } catch (err: unknown) {
        if (!cancelled) setError(errorMessage(err, "Could not load environments."))
      }
    }
    tick()
    const id = window.setInterval(tick, 8000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [refreshList])

  useEffect(() => {
    setCredSecret("")
  }, [environmentId])

  useEffect(() => {
    if (!environmentId) {
      setDetail(null)
      setStatus(null)
      setAudit([])
      return
    }
    let cancelled = false
    const tick = async () => {
      try {
        await refreshDetail(environmentId)
        if (!cancelled) setError("")
      } catch (err: unknown) {
        if (!cancelled) {
          setDetail(null)
          setStatus(null)
          setError(errorMessage(err, "Could not inspect this environment."))
        }
      }
    }
    tick()
    const id = window.setInterval(tick, 8000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [environmentId, refreshDetail])

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError("Give this room a name.")
      return
    }
    const disk = diskLimit.trim() ? Number(diskLimit) : NaN
    if (diskLimit.trim() && (!Number.isFinite(disk) || disk < 0)) {
      setError("Disk limit must be a non-negative number of megabytes.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const quotas: Record<string, number> = {}
      if (Number.isFinite(disk) && disk > 0) quotas.disk_mb = disk
      const created = await createWorkerEnvironment({
        name: trimmed,
        worker_kind: kind,
        agent_profile: agentProfile.trim() || "default",
        quotas,
      })
      setName("")
      setDiskLimit("")
      setMsg(`Created ${created.name}.`)
      await refreshList()
      navigate(`/environments/${created.id}`)
    } catch (err: unknown) {
      setError(errorMessage(err, "Could not create this environment."))
    } finally {
      setBusy(false)
    }
  }

  async function runLifecycle(
    env: WorkerEnvironmentStatus,
    action: "start" | "suspend" | "resume" | "reset" | "delete",
  ) {
    if (action === "reset") {
      const ok = window.confirm(
        `Reset “${env.name}”? Files, caches, the browser profile, and logs in this room will be wiped. The room itself stays.`,
      )
      if (!ok) return
    }
    if (action === "delete") {
      const ok = window.confirm(`Remove “${env.name}”? This cannot be undone.`)
      if (!ok) return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      if (action === "start") {
        await startWorkerEnvironment(env.id)
        setMsg(`${env.name} is running.`)
      } else if (action === "suspend") {
        await suspendWorkerEnvironment(env.id)
        setMsg(`${env.name} is paused. The agent profile is unchanged.`)
      } else if (action === "resume") {
        await resumeWorkerEnvironment(env.id)
        setMsg(`${env.name} is running again.`)
      } else if (action === "reset") {
        await resetWorkerEnvironment(env.id)
        setMsg(`${env.name} was reset.`)
      } else {
        await deleteWorkerEnvironment(env.id)
        setMsg(`${env.name} was removed.`)
        if (environmentId === env.id) navigate("/environments")
      }
      await refreshList()
      if (action !== "delete" && (environmentId === env.id || !environmentId)) {
        if (environmentId === env.id) await refreshDetail(env.id)
      }
    } catch (err: unknown) {
      setError(errorMessage(err, `Could not ${action} this environment.`))
    } finally {
      setBusy(false)
    }
  }

  async function onStoreCredential(event: FormEvent) {
    event.preventDefault()
    if (!environmentId) return
    const capability = credCapability.trim()
    const label = credLabel.trim()
    const secret = credSecret
    if (!capability || !label || !secret) {
      setError("Capability, label, and secret are required to store a key.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      await storeWorkerEnvironmentCredential(environmentId, { capability, label, secret })
      setCredSecret("")
      setCredLabel("")
      setCredCapability("")
      setMsg("Key stored. Jarvis will not show the secret again.")
      await refreshDetail(environmentId)
      await refreshList()
    } catch (err: unknown) {
      setCredSecret("")
      setError(errorMessage(err, "Could not store that key."))
    } finally {
      setBusy(false)
    }
  }

  async function onRevokeCredential(credential: WorkerEnvironmentCredential) {
    if (!environmentId || !credential.id) return
    const ok = window.confirm(`Revoke the key “${credential.label || credential.id}”? The secret cannot be recovered.`)
    if (!ok) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      await revokeWorkerEnvironmentCredential(environmentId, credential.id)
      setMsg("Key revoked.")
      await refreshDetail(environmentId)
    } catch (err: unknown) {
      setError(errorMessage(err, "Could not revoke that key."))
    } finally {
      setBusy(false)
    }
  }

  const selected = status || detail
  const selectedId = environmentId || ""

  return (
    <div className="env-page">
      <h1>Environments</h1>
      <p className="lede">
        Durable rooms for specialist workers. Files, caches, and browser state stay between jobs.
        Pausing a room does not change its agent profile.
      </p>

      {error && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--bad)", padding: "12px 16px" }}>
          {error}
        </div>
      )}
      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--gold)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}

      {selectedId && selected ? (
        <EnvironmentDetail
          env={selected}
          inspect={detail}
          audit={audit}
          busy={busy}
          credCapability={credCapability}
          credLabel={credLabel}
          credSecret={credSecret}
          onCapability={setCredCapability}
          onLabel={setCredLabel}
          onSecret={setCredSecret}
          onLifecycle={runLifecycle}
          onStoreCredential={onStoreCredential}
          onRevokeCredential={onRevokeCredential}
        />
      ) : selectedId && !selected ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <p className="lede" style={{ margin: 0 }}>
            This environment could not be opened.{" "}
            <Link to="/environments">Back to all environments</Link>
          </p>
        </div>
      ) : (
        <form className="card grid" style={{ maxWidth: 760, marginBottom: 16 }} onSubmit={onCreate}>
          <h2>New room</h2>
          <label>
            Name
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Research browser"
              aria-label="Environment name"
            />
          </label>
          <div className="env-create-row">
            <label>
              Kind of work
              <select value={kind} onChange={(event) => setKind(event.target.value)} aria-label="Worker kind">
                {KIND_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Agent profile
              <input
                type="text"
                value={agentProfile}
                onChange={(event) => setAgentProfile(event.target.value)}
                placeholder="default"
                aria-label="Agent profile"
              />
            </label>
            <label>
              Disk limit (MB, optional)
              <input
                type="number"
                min={0}
                step="any"
                value={diskLimit}
                onChange={(event) => setDiskLimit(event.target.value)}
                placeholder="No cap"
                aria-label="Disk limit in megabytes"
              />
            </label>
          </div>
          <div className="row">
            <button className="btn" type="submit" disabled={busy}>
              Create environment
            </button>
          </div>
        </form>
      )}

      <div className="card">
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>{selectedId ? "All rooms" : "Rooms on this PC"}</span>
          {selectedId && (
            <Link className="btn secondary" to="/environments">
              New room
            </Link>
          )}
        </div>
        {environments.length === 0 ? (
          <p className="lede" style={{ margin: 0 }}>
            No environments yet. Create a room so a worker can keep its files between jobs.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Disk</th>
                <th>Last active</th>
                <th>Kind</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {environments.map((env) => (
                <tr
                  key={env.id}
                  className={`env-row${env.id === selectedId ? " selected" : ""}`}
                  onClick={() => navigate(`/environments/${env.id}`)}
                >
                  <td>
                    <strong>{env.name}</strong>
                    {env.quota_violations?.length ? (
                      <div className="lede" style={{ margin: "4px 0 0" }}>
                        Over limit: {env.quota_violations.map((key) => QUOTA_LABELS[key] || key).join(", ")}
                      </div>
                    ) : null}
                  </td>
                  <td>
                    <span className={`badge ${statusBadgeClass(env.status)}`}>{statusLabel(env.status)}</span>
                  </td>
                  <td>
                    <DiskCell env={env} />
                  </td>
                  <td title={env.last_active_at}>{formatWhen(env.last_active_at)}</td>
                  <td>{kindLabel(env.worker_kind)}</td>
                  <td>
                    <div className="row env-actions" onClick={(event) => event.stopPropagation()}>
                      {env.status !== "running" && env.status !== "suspended" && (
                        <button className="btn" type="button" disabled={busy} onClick={() => runLifecycle(env, "start")}>
                          Start
                        </button>
                      )}
                      {env.status === "running" && (
                        <button className="btn secondary" type="button" disabled={busy} onClick={() => runLifecycle(env, "suspend")}>
                          Pause
                        </button>
                      )}
                      {env.status === "suspended" && (
                        <button className="btn" type="button" disabled={busy} onClick={() => runLifecycle(env, "resume")}>
                          Resume
                        </button>
                      )}
                      <button className="btn secondary" type="button" disabled={busy} onClick={() => runLifecycle(env, "reset")}>
                        Reset
                      </button>
                      <button
                        className="btn secondary"
                        type="button"
                        disabled={busy}
                        onClick={() => navigate(`/environments/${env.id}`)}
                      >
                        Inspect
                      </button>
                    </div>
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

function DiskCell({ env }: { env: WorkerEnvironmentStatus }) {
  const percent = diskPercent(env)
  const limit = diskLimitMb(env)
  return (
    <div>
      <span>{formatDisk(env)}</span>
      {percent != null && (
        <span className="env-disk-track" title={limit != null ? `${formatDisk(env)} of ${limit} MB` : undefined}>
          <span className="env-disk-fill" style={{ width: `${percent}%` }} />
        </span>
      )}
    </div>
  )
}

function EnvironmentDetail({
  env,
  inspect,
  audit,
  busy,
  credCapability,
  credLabel,
  credSecret,
  onCapability,
  onLabel,
  onSecret,
  onLifecycle,
  onStoreCredential,
  onRevokeCredential,
}: {
  env: WorkerEnvironmentStatus
  inspect: WorkerEnvironmentInspect | null
  audit: WorkerEnvironmentAuditEvent[]
  busy: boolean
  credCapability: string
  credLabel: string
  credSecret: string
  onCapability: (value: string) => void
  onLabel: (value: string) => void
  onSecret: (value: string) => void
  onLifecycle: (env: WorkerEnvironmentStatus, action: "start" | "suspend" | "resume" | "reset" | "delete") => void
  onStoreCredential: (event: FormEvent) => void
  onRevokeCredential: (credential: WorkerEnvironmentCredential) => void
}) {
  const credentials = (inspect?.credentials || []).map(publicCredential)
  const quotaEntries = Object.entries(env.quotas || {}).filter(([, value]) => value != null && value !== "")

  return (
    <div className="env-detail">
      <p className="lede" style={{ marginBottom: 12 }}>
        <Link to="/environments">← All environments</Link>
      </p>

      <div className="grid cards env-kpis">
        <div className="card">
          <div className="lede" style={{ marginBottom: 6 }}>Status</div>
          <span className={`badge ${statusBadgeClass(env.status)}`}>{statusLabel(env.status)}</span>
        </div>
        <div className="card">
          <div className="lede" style={{ marginBottom: 6 }}>Disk</div>
          <strong>{formatDisk(env)}</strong>
          {diskLimitMb(env) != null && (
            <div className="lede" style={{ margin: "6px 0 0" }}>
              Cap {diskLimitMb(env)} MB
            </div>
          )}
          {diskPercent(env) != null && (
            <span className="env-disk-track" style={{ marginTop: 8 }}>
              <span className="env-disk-fill" style={{ width: `${diskPercent(env)}%` }} />
            </span>
          )}
        </div>
        <div className="card">
          <div className="lede" style={{ marginBottom: 6 }}>Last active</div>
          <strong>{formatWhen(env.last_active_at)}</strong>
        </div>
      </div>

      {env.quota_violations?.length ? (
        <div className="card" style={{ marginTop: 16, borderLeft: "4px solid var(--warn)", padding: "12px 16px" }}>
          Over the set limits: {env.quota_violations.map((key) => QUOTA_LABELS[key] || key).join(", ")}. Start and resume stay blocked until usage drops or the cap is raised.
        </div>
      ) : null}

      <div className="card" style={{ marginTop: 16 }}>
        <h2>{env.name}</h2>
        <div className="kv" style={{ marginBottom: 16 }}>
          <b>Kind of work</b>
          <span>{kindLabel(env.worker_kind)}</span>
          <b>Agent profile</b>
          <span>{env.agent_profile || "default"}</span>
          <b>Created</b>
          <span>{formatWhen(env.created_at)}</span>
          {env.suspended_at ? (
            <>
              <b>Paused at</b>
              <span>{formatWhen(env.suspended_at)}</span>
            </>
          ) : null}
          {quotaEntries.map(([key, value]) => (
            <Fragment key={key}>
              <b>{QUOTA_LABELS[key] || key.replaceAll("_", " ")}</b>
              <span>{formatQuotaValue(key, value)}</span>
            </Fragment>
          ))}
        </div>
        <div className="row">
          {env.status !== "running" && env.status !== "suspended" && (
            <button className="btn" type="button" disabled={busy} onClick={() => onLifecycle(env, "start")}>
              Start
            </button>
          )}
          {env.status === "running" && (
            <button className="btn secondary" type="button" disabled={busy} onClick={() => onLifecycle(env, "suspend")}>
              Pause
            </button>
          )}
          {env.status === "suspended" && (
            <button className="btn" type="button" disabled={busy} onClick={() => onLifecycle(env, "resume")}>
              Resume
            </button>
          )}
          <button className="btn secondary" type="button" disabled={busy} onClick={() => onLifecycle(env, "reset")}>
            Reset
          </button>
          <button className="btn danger" type="button" disabled={busy} onClick={() => onLifecycle(env, "delete")}>
            Remove
          </button>
        </div>
      </div>

      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Inspect</h2>
          {!inspect ? (
            <p className="lede" style={{ margin: 0 }}>Loading this room…</p>
          ) : (
            <>
              <div className="kv" style={{ marginBottom: 16 }}>
                <b>Folder on this PC</b>
                <span className="stat">{inspect.workspace_path || "—"}</span>
                <b>Caches</b>
                <span className="stat">{inspect.caches_path || "—"}</span>
                <b>Browser profile</b>
                <span className="stat">{inspect.browser_profile_path || "—"}</span>
                <b>Logs</b>
                <span className="stat">{inspect.logs_path || "—"}</span>
              </div>
              <h3 className="env-subhead">Files in this room</h3>
              {inspect.workspace_files?.length ? (
                <ul className="env-file-list">
                  {inspect.workspace_files.map((file) => (
                    <li key={file}>{file}</li>
                  ))}
                </ul>
              ) : (
                <p className="lede">No files yet.</p>
              )}
              <h3 className="env-subhead">Log files</h3>
              {inspect.log_files?.length ? (
                <ul className="env-file-list">
                  {inspect.log_files.map((file) => (
                    <li key={file}>{file}</li>
                  ))}
                </ul>
              ) : (
                <p className="lede">No logs yet.</p>
              )}
              <h3 className="env-subhead">Background processes</h3>
              {inspect.processes?.length ? (
                <pre className="env-json">{JSON.stringify(inspect.processes, null, 2)}</pre>
              ) : (
                <p className="lede">None recorded.</p>
              )}
              <h3 className="env-subhead">Task state</h3>
              {inspect.task_state && Object.keys(inspect.task_state).length ? (
                <pre className="env-json">{JSON.stringify(inspect.task_state, null, 2)}</pre>
              ) : (
                <p className="lede">None recorded.</p>
              )}
            </>
          )}
        </div>

        <div className="card">
          <h2>Stored keys</h2>
          <p className="lede">
            Keys are scoped to this room and a capability. Jarvis never shows the secret after you save it.
          </p>
          {credentials.length === 0 ? (
            <p className="lede">No keys stored.</p>
          ) : (
            credentials.map((credential) => (
              <div className="toggle" key={credential.id || `${credential.label}-${credential.capability}`}>
                <div>
                  <strong>{credential.label || "Untitled key"}</strong>
                  <div className="lede" style={{ margin: 0 }}>
                    For {credential.capability || "unspecified"}
                    {credential.created_at ? ` · stored ${formatWhen(credential.created_at)}` : ""}
                    {credential.revoked_at ? ` · revoked ${formatWhen(credential.revoked_at)}` : ""}
                  </div>
                </div>
                {credential.id && !credential.revoked_at && (
                  <button
                    className="btn secondary"
                    type="button"
                    disabled={busy}
                    onClick={() => onRevokeCredential(credential)}
                  >
                    Revoke
                  </button>
                )}
              </div>
            ))
          )}
          <form className="grid" style={{ gap: 10, marginTop: 16 }} autoComplete="off" onSubmit={onStoreCredential}>
            <label>
              Used for
              <input
                type="text"
                value={credCapability}
                onChange={(event) => onCapability(event.target.value)}
                placeholder="browser, git, web_fetch"
                autoComplete="off"
                aria-label="Credential capability"
              />
            </label>
            <label>
              Label
              <input
                type="text"
                value={credLabel}
                onChange={(event) => onLabel(event.target.value)}
                placeholder="Session cookie"
                autoComplete="off"
                aria-label="Credential label"
              />
            </label>
            <label>
              Secret
              <input
                type="password"
                value={credSecret}
                onChange={(event) => onSecret(event.target.value)}
                autoComplete="new-password"
                aria-label="Credential secret"
              />
            </label>
            <button className="btn" type="submit" disabled={busy}>
              Store key
            </button>
          </form>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16, marginBottom: 16 }}>
        <h2>Activity</h2>
        {audit.length === 0 ? (
          <p className="lede" style={{ margin: 0 }}>No recorded events yet.</p>
        ) : (
          <div className="timeline">
            {[...audit].reverse().map((event, index) => (
              <div className="t-item" key={`${event.timestamp}-${event.event}-${index}`}>
                <div className="rail" />
                <div>
                  <strong>{eventLabel(event.event)}</strong>
                  <p>
                    {formatWhen(event.timestamp)}
                    {event.credential_id ? " · key change" : ""}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
