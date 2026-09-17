import { useCallback, useEffect, useMemo, useState } from "react"
import {
  configureHexStrike,
  getHexStrikeOperatorJob,
  getHexStrikeStatus,
  getHexStrikeToolInstallJob,
  installHexStrike,
  installHexStrikeTool,
  listHexStrikeOperatorJobs,
  listHexStrikeScopes,
  operateHexStrike,
  refreshHexStrikeToolsCatalog,
  startHexStrike,
  stopHexStrike,
  stopHexStrikeOperatorJob,
  type HexStrikeCatalogItem,
  type HexStrikeOperatorJob,
  type HexStrikeScope,
  type HexStrikeStatus,
} from "../api"
import { extractPendingApprovalError } from "../chat/approvalsApi"
import { usePendingApprovals } from "../chat/pendingApprovals"
import "./hexstrike.css"

const CATALOG_PAGE_SIZE = 24

type DaybreakTab = "runtime" | "catalog" | "operate" | "jobs"

function isOperableCapability(item: HexStrikeCatalogItem): boolean {
  if (item.source === "dependency") return false
  if (item.id.startsWith("dep:")) return false
  return true
}

function installToolId(item: HexStrikeCatalogItem): string {
  if (item.install_id) return item.install_id
  if (item.id.startsWith("dep:")) return item.id.slice(4)
  return item.id
}

function defaultArgsJson(item: HexStrikeCatalogItem | null): string {
  if (!item) return "{}"
  if (item.source === "defensive") {
    return JSON.stringify({ scope_id: "", options: {} }, null, 2)
  }
  const schema = item.input_schema
  if (schema?.properties && typeof schema.properties === "object") {
    const props = schema.properties as Record<string, { default?: unknown }>
    const seed: Record<string, unknown> = {}
    for (const [key, meta] of Object.entries(props)) {
      if (meta && "default" in meta) seed[key] = meta.default
    }
    return JSON.stringify(seed, null, 2)
  }
  return "{}"
}

function operatorLabel(status: HexStrikeStatus | null): string {
  const op = status?.operator
  if (!status?.running) return "Suite offline"
  if (op?.operator_ready) return "Operator ready"
  if (status.catalog_stale || op?.catalog_stale) return "Catalog stale — refresh"
  return "Surface syncing"
}

export function HudHexStrikeSuite() {
  const { registerFrom428 } = usePendingApprovals()
  const [status, setStatus] = useState<HexStrikeStatus | null>(null)
  const [scopes, setScopes] = useState<HexStrikeScope[]>([])
  const [pathDraft, setPathDraft] = useState("")
  const [tab, setTab] = useState<DaybreakTab>("runtime")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [loadError, setLoadError] = useState<string | null>(null)

  const [catalogPage, setCatalogPage] = useState(0)
  const [catalogFilter, setCatalogFilter] = useState("")

  const [operateCapabilityId, setOperateCapabilityId] = useState("")
  const [argsJson, setArgsJson] = useState("{}")
  const [argsError, setArgsError] = useState("")

  const [jobs, setJobs] = useState<HexStrikeOperatorJob[]>([])
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [jobDetail, setJobDetail] = useState<HexStrikeOperatorJob | null>(null)

  const [pendingInstallJobs, setPendingInstallJobs] = useState<Set<string>>(new Set())

  const refresh = useCallback(async () => {
    try {
      const [next, scopeResult, jobList] = await Promise.all([
        getHexStrikeStatus(),
        listHexStrikeScopes(),
        listHexStrikeOperatorJobs(),
      ])
      setStatus(next)
      setScopes(scopeResult.scopes)
      setJobs(jobList.jobs || [])
      setPathDraft((prev) => prev || next.install_path || "")
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load HexStrike status.")
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 2500)
    return () => window.clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    if (!selectedJobId) {
      setJobDetail(null)
      return
    }
    let cancelled = false
    const load = async () => {
      try {
        const detail = await getHexStrikeOperatorJob(selectedJobId)
        if (!cancelled) setJobDetail(detail)
      } catch (err) {
        if (!cancelled) setMsg(err instanceof Error ? err.message : "Job detail unavailable.")
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [selectedJobId])

  useEffect(() => {
    if (!pendingInstallJobs.size) return
    const timer = window.setInterval(async () => {
      const ids = [...pendingInstallJobs]
      let changed = false
      for (const id of ids) {
        try {
          const job = await getHexStrikeToolInstallJob(id)
          if (job.status === "ready" || job.status === "error") {
            setPendingInstallJobs((prev) => {
              const next = new Set(prev)
              next.delete(id)
              return next
            })
            changed = true
            if (job.status === "error") {
              setMsg(job.detail || `Install failed for ${job.dependency_id}`)
            } else {
              setMsg(`Installed ${job.dependency_id}`)
            }
          }
        } catch {
          // keep polling until resolved or user refreshes
        }
      }
      if (changed) void refresh()
    }, 1500)
    return () => window.clearInterval(timer)
  }, [pendingInstallJobs, refresh])

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true)
    setMsg("")
    setLoadError(null)
    try {
      await action()
      setMsg(success)
      await refresh()
    } catch (err) {
      const parked = extractPendingApprovalError(err)
      if (parked) {
        registerFrom428(parked)
        setMsg("Approval required — choose Allow, Always allow, or Deny in the popup.")
        setLoadError(null)
        return
      }
      const text = err instanceof Error ? err.message : "HexStrike action failed."
      setMsg(text)
      setLoadError(text)
    } finally {
      setBusy(false)
    }
  }

  const catalog = useMemo(() => status?.catalog || [], [status?.catalog])
  const filteredCatalog = useMemo(() => {
    const q = catalogFilter.trim().toLowerCase()
    if (!q) return catalog
    return catalog.filter(
      (item) =>
        item.id.toLowerCase().includes(q) ||
        item.title.toLowerCase().includes(q) ||
        item.source.toLowerCase().includes(q),
    )
  }, [catalog, catalogFilter])

  const catalogPageCount = Math.max(1, Math.ceil(filteredCatalog.length / CATALOG_PAGE_SIZE))
  const catalogSlice = filteredCatalog.slice(
    catalogPage * CATALOG_PAGE_SIZE,
    catalogPage * CATALOG_PAGE_SIZE + CATALOG_PAGE_SIZE,
  )

  const operable = useMemo(() => catalog.filter(isOperableCapability), [catalog])
  const selectedCapability = operable.find((item) => item.id === operateCapabilityId) || null

  useEffect(() => {
    if (!operateCapabilityId && operable.length) {
      setOperateCapabilityId(operable[0].id)
      setArgsJson(defaultArgsJson(operable[0]))
    }
  }, [operable, operateCapabilityId])

  const live = !!status?.running
  const install = status?.install
  const stateLabel = status?.starting ? "Igniting" : live ? "Live" : status?.installed ? "Standby" : "Not installed"
  const op = status?.operator
  const depJobs = status?.dependency_install_jobs || {}

  const hasRunningJob = jobs.some((j) => j.status === "running")

  return (
    <div className="hex-suite" aria-label="Daybreak HexStrike operator console">
      <div className="hex-suite-frame" aria-hidden />
      <header className="hex-suite-head">
        <div className="hex-suite-mark" aria-hidden>⬡</div>
        <div className="hex-suite-titles">
          <strong>Daybreak</strong>
          <span>HexStrike operator console · loopback suite</span>
        </div>
        <span className={`hex-suite-pill${live ? " live" : ""}`}>{stateLabel}</span>
      </header>

      <nav className="hex-suite-tabs" aria-label="Daybreak sections">
        {(
          [
            ["runtime", "Runtime"],
            ["catalog", `Catalog (${status?.catalog_count ?? catalog.length})`],
            ["operate", "Operate"],
            ["jobs", `Jobs (${jobs.length})`],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`hex-suite-tab${tab === id ? " active" : ""}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {loadError && (
        <p className="hex-suite-banner error" role="alert">
          {loadError}
        </p>
      )}

      <div className="hex-suite-grid hex-suite-grid-wide">
        {tab === "runtime" && (
          <>
            <section className="hex-panel">
              <h2>Lifecycle</h2>
              <dl>
                <div>
                  <dt>Bind</dt>
                  <dd>
                    {status?.host || "127.0.0.1"}:{status?.port || 8888}
                  </dd>
                </div>
                <div>
                  <dt>PID</dt>
                  <dd>{status?.pid ?? "—"}</dd>
                </div>
                <div>
                  <dt>Commit</dt>
                  <dd title={install?.approved_commit}>{install?.approved_commit?.slice(0, 10) || "—"}</dd>
                </div>
              </dl>
              {status?.last_error && <p className="hex-suite-error">{status.last_error}</p>}
              <div className="hex-btn-row">
                <button
                  type="button"
                  className="hex-suite-btn"
                  disabled={busy || live}
                  onClick={() => void run(startHexStrike, "HexStrike started on loopback.")}
                >
                  Start
                </button>
                <button
                  type="button"
                  className="hex-suite-btn ghost"
                  disabled={busy || !live}
                  onClick={() => void run(stopHexStrike, "HexStrike stopped.")}
                >
                  Stop
                </button>
              </div>
            </section>

            <section className="hex-panel">
              <h2>Operator readiness</h2>
              <dl>
                <div>
                  <dt>Ready</dt>
                  <dd>{op?.operator_ready ? "yes" : "no"}</dd>
                </div>
                <div>
                  <dt>Catalog</dt>
                  <dd>
                    {status?.catalog_count ?? catalog.length}
                    {status?.catalog_stale ? " (stale)" : ""}
                  </dd>
                </div>
                <div>
                  <dt>MCP</dt>
                  <dd>{op?.mcp?.ok ? "registered" : "pending"}</dd>
                </div>
              </dl>
              <p className="hex-suite-hint">{operatorLabel(status)}</p>
              {(status?.mcp_error || op?.mcp?.error) && (
                <p className="hex-suite-error">{status?.mcp_error || op?.mcp?.error}</p>
              )}
              <button
                type="button"
                className="hex-suite-btn"
                disabled={busy || !live}
                onClick={() =>
                  void run(async () => {
                    await refreshHexStrikeToolsCatalog()
                  }, "Operator catalog refreshed.")
                }
              >
                Refresh catalog
              </button>
            </section>

            <section className="hex-panel hex-panel-wide">
              <h2>Install / repair</h2>
              <div className="hex-progress">
                <span style={{ width: `${install?.progress || 0}%` }} />
              </div>
              <p className="hex-suite-hint">
                {install?.stage || "idle"} · {install?.progress || 0}%
              </p>
              {install?.error && <p className="hex-suite-error">{install.error}</p>}
              <button
                type="button"
                className="hex-suite-btn"
                disabled={busy || install?.state === "running"}
                onClick={() =>
                  void run(() => installHexStrike(pathDraft), "Pinned HexStrike install/repair started.")
                }
              >
                {install?.state === "running" ? "Installing…" : status?.installed ? "Repair" : "Install"}
              </button>
            </section>
          </>
        )}

        {tab === "catalog" && (
          <section className="hex-panel hex-panel-wide hex-panel-catalog">
            <div className="hex-catalog-toolbar">
              <h2>Discovered tools</h2>
              <input
                className="hex-catalog-search"
                aria-label="Filter catalog"
                placeholder="Filter by id, title, source…"
                value={catalogFilter}
                onChange={(e) => {
                  setCatalogFilter(e.target.value)
                  setCatalogPage(0)
                }}
              />
              <button
                type="button"
                className="hex-suite-btn ghost"
                disabled={busy || !live}
                onClick={() =>
                  void run(async () => {
                    await refreshHexStrikeToolsCatalog()
                  }, "Catalog refreshed from live suite.")
                }
              >
                Sync
              </button>
            </div>
            {!catalog.length && (
              <p className="hex-suite-hint">
                {live
                  ? "No catalog rows yet — use Refresh catalog on Runtime."
                  : "Start the suite to discover tools."}
              </p>
            )}
            <ul className="hex-catalog-list">
              {catalogSlice.map((item) => {
                const missing = item.available === false
                const installTarget =
                  item.install_id || item.missing_dependencies?.[0] || installToolId(item)
                const canInstall =
                  missing &&
                  (item.source === "dependency" ||
                    item.id.startsWith("dep:") ||
                    !!item.install_id ||
                    !!item.missing_dependencies?.length)
                return (
                  <li key={item.id} className={missing ? "missing" : "ok"}>
                    <span className="hex-catalog-id">{item.id}</span>
                    <span className="hex-catalog-title">{item.title}</span>
                    <span className="hex-catalog-src">{item.source}</span>
                    {canInstall && (
                      <button
                        type="button"
                        className="hex-suite-btn ghost compact"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            const job = await installHexStrikeTool(installTarget)
                            setPendingInstallJobs((prev) => new Set(prev).add(job.id))
                          }, `Install queued for ${installTarget}.`)
                        }
                      >
                        Install
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
            {filteredCatalog.length > CATALOG_PAGE_SIZE && (
              <div className="hex-catalog-pager">
                <button
                  type="button"
                  className="hex-suite-btn ghost compact"
                  disabled={catalogPage <= 0}
                  onClick={() => setCatalogPage((p) => Math.max(0, p - 1))}
                >
                  Prev
                </button>
                <span className="hex-suite-hint">
                  {catalogPage + 1} / {catalogPageCount} · {filteredCatalog.length} tools
                </span>
                <button
                  type="button"
                  className="hex-suite-btn ghost compact"
                  disabled={catalogPage >= catalogPageCount - 1}
                  onClick={() => setCatalogPage((p) => Math.min(catalogPageCount - 1, p + 1))}
                >
                  Next
                </button>
              </div>
            )}
            {Object.keys(depJobs).length > 0 && (
              <div className="hex-install-jobs">
                <h3>Dependency installs</h3>
                <ul className="hex-proc-list">
                  {Object.values(depJobs).map((job) => (
                    <li key={job.id}>
                      {job.dependency_id}: {job.status}
                      {job.detail ? ` — ${job.detail.slice(0, 80)}` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {tab === "operate" && (
          <section className="hex-panel hex-panel-wide">
            <h2>Invoke capability</h2>
            {!operable.length && (
              <p className="hex-suite-hint">
                {live
                  ? "Refresh the operator catalog to load MCP and HTTP capabilities."
                  : "Start HexStrike before operating."}
              </p>
            )}
            <div className="hex-form">
              <select
                aria-label="Capability"
                value={operateCapabilityId}
                onChange={(e) => {
                  const id = e.target.value
                  setOperateCapabilityId(id)
                  const cap = operable.find((item) => item.id === id)
                  setArgsJson(defaultArgsJson(cap || null))
                  setArgsError("")
                }}
              >
                {operable.map((item) => (
                  <option key={item.id} value={item.id} disabled={item.available === false}>
                    {item.id} — {item.title}
                    {item.available === false ? " (unavailable)" : ""}
                  </option>
                ))}
              </select>
              {selectedCapability?.source === "defensive" && scopes.length > 0 && (
                <select
                  aria-label="Scope for defensive capability"
                  onChange={(e) => {
                    try {
                      const parsed = JSON.parse(argsJson) as Record<string, unknown>
                      parsed.scope_id = e.target.value
                      setArgsJson(JSON.stringify(parsed, null, 2))
                    } catch {
                      setArgsJson(JSON.stringify({ scope_id: e.target.value, options: {} }, null, 2))
                    }
                  }}
                >
                  <option value="">Quick-fill scope_id</option>
                  {scopes.map((scope) => (
                    <option key={scope.id} value={scope.id}>
                      {scope.label || scope.id}
                    </option>
                  ))}
                </select>
              )}
              <label className="hex-args-label">
                Arguments (JSON)
                <textarea
                  className="hex-args-editor"
                  aria-label="Capability arguments JSON"
                  value={argsJson}
                  spellCheck={false}
                  onChange={(e) => {
                    setArgsJson(e.target.value)
                    setArgsError("")
                  }}
                />
              </label>
              {argsError && <p className="hex-suite-error">{argsError}</p>}
            </div>
            <button
              type="button"
              className="hex-suite-btn"
              disabled={busy || !live || !operateCapabilityId || selectedCapability?.available === false}
              onClick={() =>
                void run(async () => {
                  let args: Record<string, unknown>
                  try {
                    args = JSON.parse(argsJson) as Record<string, unknown>
                  } catch {
                    setArgsError("Arguments must be valid JSON.")
                    throw new Error("Invalid JSON arguments")
                  }
                  const job = await operateHexStrike({
                    capability_id: operateCapabilityId,
                    arguments: args,
                  })
                  setSelectedJobId(job.id)
                  setTab("jobs")
                }, "Operator job started.")
              }
            >
              Run capability
            </button>
            <p className="hex-suite-hint">
              Sources: defensive:*, http:*, mcp:* — dependency rows install from Catalog.
            </p>
          </section>
        )}

        {tab === "jobs" && (
          <>
            <section className="hex-panel">
              <h2>Operator jobs</h2>
              {hasRunningJob && <p className="hex-suite-hint">Polling while jobs are running…</p>}
              <ul className="hex-job-list">
                {jobs.length === 0 && <li className="hex-suite-hint">No operator jobs yet.</li>}
                {[...jobs].reverse().map((job) => (
                  <li key={job.id}>
                    <button
                      type="button"
                      className={`hex-job-row${selectedJobId === job.id ? " selected" : ""}`}
                      onClick={() => setSelectedJobId(job.id)}
                    >
                      <span className={`hex-job-status ${job.status}`}>{job.status}</span>
                      <span className="hex-job-cap">{job.capability_id}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            <section className="hex-panel hex-panel-wide">
              <h2>Job detail</h2>
              {!jobDetail && <p className="hex-suite-hint">Select a job to view logs and artifacts.</p>}
              {jobDetail && (
                <>
                  <dl className="hex-job-meta">
                    <div>
                      <dt>ID</dt>
                      <dd>{jobDetail.id}</dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>{jobDetail.status}</dd>
                    </div>
                    <div>
                      <dt>Capability</dt>
                      <dd>{jobDetail.capability_id}</dd>
                    </div>
                    <div>
                      <dt>Started</dt>
                      <dd>{jobDetail.started_at}</dd>
                    </div>
                    {jobDetail.finished_at && (
                      <div>
                        <dt>Finished</dt>
                        <dd>{jobDetail.finished_at}</dd>
                      </div>
                    )}
                  </dl>
                  {jobDetail.error && <p className="hex-suite-error">{jobDetail.error}</p>}
                  {jobDetail.log_tail && (
                    <pre className="hex-suite-json hex-job-log">{jobDetail.log_tail}</pre>
                  )}
                  {(jobDetail.artifacts?.length || jobDetail.artifact_paths?.length) && (
                    <ul className="hex-proc-list">
                      {(jobDetail.artifacts || []).map((art) => (
                        <li key={art.path} title={art.path}>
                          {art.name} ({art.size} B)
                        </li>
                      ))}
                      {!jobDetail.artifacts?.length &&
                        jobDetail.artifact_paths?.map((path) => (
                          <li key={path} title={path}>
                            {path.split(/[/\\]/).pop()}
                          </li>
                        ))}
                    </ul>
                  )}
                  {jobDetail.status === "running" && (
                    <button
                      type="button"
                      className="hex-suite-btn ghost"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => stopHexStrikeOperatorJob(jobDetail.id),
                          "Stop requested for tracked job.",
                        )
                      }
                    >
                      Stop job
                    </button>
                  )}
                </>
              )}
            </section>
          </>
        )}
      </div>

      <footer className="hex-suite-foot">
        <label>
          Install path
          <input
            value={pathDraft}
            onChange={(event) => setPathDraft(event.target.value)}
            placeholder="runtime/hexstrike-ai"
            spellCheck={false}
          />
        </label>
        <button
          type="button"
          className="hex-suite-btn ghost"
          disabled={busy}
          onClick={() => void run(() => configureHexStrike({ install_path: pathDraft }), "Install path saved.")}
        >
          Save path
        </button>
        <a className="hex-suite-help" href="/help?topic=hexstrike-blue">HexStrike setup help</a>
        {msg && <span className="hex-suite-msg" role="status">{msg}</span>}
      </footer>
    </div>
  )
}
