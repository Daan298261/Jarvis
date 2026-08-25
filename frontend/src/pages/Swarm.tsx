import { Fragment, useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  createNodeLease,
  getNodeBudget,
  getNodeRolePolicies,
  getSwarmNode,
  listNodeLeases,
  listSwarmNodes,
  listSwarmRoles,
  postSwarmPlacement,
  putNodeBudget,
  putNodeRolePolicy,
  releaseNodeLease,
  SWARM_BUDGET_PRESETS,
  SWARM_ROLE_NAMES,
  SWARM_ROLE_POLICY_LEVELS,
  type SwarmLease,
  type SwarmNode,
  type SwarmNodeBudget,
  type SwarmBudgetUpdate,
  type SwarmNodeHardware,
  type SwarmNodeResources,
  type SwarmResourceAmounts,
  type SwarmPlacementResult,
  type SwarmRoleHolder,
  type SwarmRolePolicy,
  type SwarmRolesResponse,
  type SwarmWorker,
} from "../api"

function statusBadgeClass(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === "online") return "completed"
  if (normalized === "offline") return "failed"
  return "queued"
}

function workerStatusBadgeClass(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === "ready" || normalized === "available" || normalized === "online") return "completed"
  if (normalized === "running" || normalized === "waiting") return "running"
  if (normalized === "error" || normalized === "failed" || normalized === "not_loaded") return "failed"
  return "queued"
}

function leaseStatusBadgeClass(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === "active") return "running"
  if (normalized === "released") return "completed"
  if (normalized === "expired") return "failed"
  return "queued"
}

function formatResourceAmounts(amounts: SwarmResourceAmounts | undefined): string {
  if (!amounts) return "—"
  const parts: string[] = []
  if (amounts.cpu != null) parts.push(`CPU ${formatNumber(amounts.cpu)} threads`)
  if (amounts.ram != null) parts.push(`RAM ${formatNumber(amounts.ram)} GB`)
  if (amounts.gpu != null) parts.push(`GPU ${formatNumber(amounts.gpu)}%`)
  if (amounts.vram != null) parts.push(`VRAM ${formatNumber(amounts.vram)} MiB`)
  if (amounts.disk != null) parts.push(`Disk ${formatNumber(amounts.disk)} GB`)
  if (amounts.network != null) parts.push(`Network ${formatNumber(amounts.network)} Mbps`)
  return parts.length ? parts.join(" · ") : "—"
}

function formatNumber(value: number): string {
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(2).replace(/\.?0+$/, "")
}

function formatLeaseClaim(claim: SwarmLease["claim"]): string {
  const parts: string[] = []
  if (claim.cpu_threads != null) parts.push(`${claim.cpu_threads} threads`)
  if (claim.ram_gb != null) parts.push(`${claim.ram_gb} GB RAM`)
  if (claim.gpu_percent != null) parts.push(`${claim.gpu_percent}% GPU`)
  if (claim.vram_mib != null) parts.push(`${claim.vram_mib} MiB VRAM`)
  if (claim.disk_gb != null) parts.push(`${claim.disk_gb} GB disk`)
  if (claim.network_mbps != null) parts.push(`${claim.network_mbps} Mbps`)
  return parts.length ? parts.join(" · ") : "—"
}

function formatRoles(roles: string[] | undefined): string {
  if (!roles?.length) return "—"
  return roles.join(", ")
}

function formatResources(resources: SwarmNodeResources | undefined): string {
  if (!resources) return "—"
  const parts: string[] = []
  if (resources.cpu_cores != null) parts.push(`${resources.cpu_cores} cores`)
  if (resources.cpu_threads != null) parts.push(`${resources.cpu_threads} threads`)
  if (resources.ram_available_gb != null) {
    const total = resources.ram_total_gb != null ? `${resources.ram_total_gb} GB` : "?"
    parts.push(`${resources.ram_available_gb}/${total} RAM`)
  }
  if (resources.vram_free_mib != null) {
    const total = resources.vram_total_mib != null ? `${resources.vram_total_mib}` : "?"
    parts.push(`${resources.vram_free_mib}/${total} MiB VRAM`)
  }
  if (resources.disk_free_gb != null) {
    const total = resources.disk_total_gb != null ? `${resources.disk_total_gb} GB` : "?"
    parts.push(`${resources.disk_free_gb}/${total} disk`)
  }
  if (resources.gpu_name) parts.push(resources.gpu_name)
  return parts.length ? parts.join(" · ") : "—"
}

function formatHardware(hardware: SwarmNodeHardware | undefined): string {
  if (!hardware) return "—"
  const parts: string[] = []
  if (hardware.cpu_name) parts.push(hardware.cpu_name)
  if (hardware.gpu_name) parts.push(hardware.gpu_name)
  if (hardware.os_name) {
    parts.push(`${hardware.os_name}${hardware.os_version ? ` ${hardware.os_version}` : ""}`)
  }
  return parts.length ? parts.join(" · ") : "—"
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—"
  return value.replace("T", " ").slice(0, 19)
}

function ObjectKv({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([, value]) => value != null && value !== "")
  if (!entries.length) return <p className="lede">No data</p>
  return (
    <div className="kv">
      {entries.map(([key, value]) => (
        <Fragment key={key}>
          <b>{key.replaceAll("_", " ")}</b>
          <span>{typeof value === "boolean" ? (value ? "yes" : "no") : String(value)}</span>
        </Fragment>
      ))}
    </div>
  )
}

function RoleCard({ title, holder }: { title: string; holder: SwarmRoleHolder | null }) {
  if (!holder) {
    return (
      <div className="card">
        <h2>{title}</h2>
        <p className="lede" style={{ margin: 0 }}>Unassigned</p>
      </div>
    )
  }
  return (
    <div className="card">
      <h2>{title}</h2>
      <div className="kv">
        <b>Role</b><span>{holder.role}</span>
        <b>Hostname</b><span>{holder.hostname || "—"}</span>
        <b>Node ID</b>
        <span>
          <Link to={`/swarm/${holder.node_id}`} className="stat">{holder.node_id}</Link>
        </span>
        <b>Assignment</b><span>{holder.assignment}</span>
      </div>
    </div>
  )
}

function PlacementSection({
  onPlaced,
}: {
  onPlaced: () => Promise<void>
}) {
  const [capabilities, setCapabilities] = useState("")
  const [role, setRole] = useState("")
  const [cpuThreads, setCpuThreads] = useState("")
  const [ramGb, setRamGb] = useState("")
  const [ttlSeconds, setTtlSeconds] = useState("300")
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<SwarmPlacementResult | null>(null)

  async function handleSubmit() {
    setSubmitting(true)
    setSubmitError(null)
    try {
      const capabilityList = capabilities
        .split(/[,\s]+/)
        .map((value) => value.trim())
        .filter(Boolean)
      const body: {
        capabilities: string[]
        role?: string
        claim?: { cpu_threads?: number; ram_gb?: number }
        ttl_seconds?: number
      } = { capabilities: capabilityList }
      if (role) body.role = role

      const claim: { cpu_threads?: number; ram_gb?: number } = {}
      if (cpuThreads.trim()) {
        const value = Number(cpuThreads)
        if (!Number.isFinite(value) || value <= 0) {
          throw new Error("cpu_threads must be a positive number")
        }
        claim.cpu_threads = value
      }
      if (ramGb.trim()) {
        const value = Number(ramGb)
        if (!Number.isFinite(value) || value <= 0) {
          throw new Error("ram_gb must be a positive number")
        }
        claim.ram_gb = value
      }
      if (Object.keys(claim).length) body.claim = claim

      if (ttlSeconds.trim()) {
        const ttl = Number(ttlSeconds)
        if (!Number.isFinite(ttl) || ttl <= 0) {
          throw new Error("ttl_seconds must be a positive number")
        }
        body.ttl_seconds = ttl
      }

      const placement = await postSwarmPlacement(body)
      setResult(placement)
      if (placement.accepted) {
        await onPlaced()
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Placement request failed")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2 style={{ marginTop: 0 }}>Placement</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Request work placement via <code>POST /api/swarm/placement</code>. Empty capabilities place on localhost.
      </p>
      {submitError && (
        <p className="lede" style={{ margin: "0 0 10px", color: "var(--bad)" }}>
          {submitError}
        </p>
      )}
      <div className="grid" style={{ gap: 10, maxWidth: 520 }}>
        <label className="row" style={{ alignItems: "center", gap: 12 }}>
          <span style={{ minWidth: 110 }}>Capabilities</span>
          <input
            type="text"
            value={capabilities}
            disabled={submitting}
            onChange={(e) => setCapabilities(e.target.value)}
            placeholder="comma-separated (empty = localhost)"
          />
        </label>
        <label className="row" style={{ alignItems: "center", gap: 12 }}>
          <span style={{ minWidth: 110 }}>Role</span>
          <select value={role} disabled={submitting} onChange={(e) => setRole(e.target.value)}>
            <option value="">none</option>
            {SWARM_ROLE_NAMES.map((value) => (
              <option key={value} value={value}>{formatRoleLabel(value)}</option>
            ))}
          </select>
        </label>
        <label className="row" style={{ alignItems: "center", gap: 12 }}>
          <span style={{ minWidth: 110 }}>CPU threads</span>
          <input
            type="number"
            min={1}
            value={cpuThreads}
            disabled={submitting}
            onChange={(e) => setCpuThreads(e.target.value)}
            placeholder="optional claim"
          />
        </label>
        <label className="row" style={{ alignItems: "center", gap: 12 }}>
          <span style={{ minWidth: 110 }}>RAM (GB)</span>
          <input
            type="number"
            min={0.1}
            step={0.1}
            value={ramGb}
            disabled={submitting}
            onChange={(e) => setRamGb(e.target.value)}
            placeholder="optional claim"
          />
        </label>
        <label className="row" style={{ alignItems: "center", gap: 12 }}>
          <span style={{ minWidth: 110 }}>TTL (seconds)</span>
          <input
            type="number"
            min={1}
            value={ttlSeconds}
            disabled={submitting}
            onChange={(e) => setTtlSeconds(e.target.value)}
          />
        </label>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn secondary" type="button" disabled={submitting} onClick={handleSubmit}>
            {submitting ? "Placing…" : "Place work"}
          </button>
        </div>
      </div>
      {result && (
        <div
          style={{
            marginTop: 16,
            padding: "12px 14px",
            borderLeft: `4px solid ${result.accepted ? "var(--good)" : "var(--bad)"}`,
            background: "var(--panel)",
          }}
        >
          <div className="row" style={{ gap: 10, marginBottom: 8 }}>
            <strong>Last result</strong>
            <span className={`badge ${result.accepted ? "completed" : "failed"}`}>
              {result.accepted ? "Accepted" : "Rejected"}
            </span>
          </div>
          {result.accepted ? (
            <div className="kv">
              <b>Reason</b><span>{result.reason}</span>
              <b>Node</b>
              <span>
                <Link to={`/swarm/${result.node_id}`} className="stat">
                  {result.hostname || result.node_id}
                </Link>
                <span className="stat" style={{ marginLeft: 8 }}>{result.node_id}</span>
              </span>
              <b>Worker</b>
              <span>
                {result.worker.name} ({result.worker.kind}) ·{" "}
                <span className={`badge ${workerStatusBadgeClass(result.worker.status)}`}>
                  {result.worker.status}
                </span>
                <span className="stat" style={{ marginLeft: 8 }}>{result.worker.id}</span>
              </span>
              {result.lease && (
                <>
                  <b>Lease</b>
                  <span>
                    <span className={`badge ${leaseStatusBadgeClass(result.lease.status)}`}>
                      {result.lease.status}
                    </span>
                    {" · "}
                    {formatLeaseClaim(result.lease.claim)}
                    <span className="stat" style={{ marginLeft: 8 }}>{result.lease.id}</span>
                  </span>
                </>
              )}
            </div>
          ) : (
            <div className="kv">
              <b>Code</b><span className="stat">{result.code}</span>
              <b>Reason</b><span>{result.reason}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function RolesSection({
  roles,
  error,
  loading,
}: {
  roles: SwarmRolesResponse | null
  error: string | null
  loading: boolean
}) {
  if (error) {
    return (
      <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--warn)", padding: "12px 16px" }}>
        <strong>Roles API unavailable</strong>
        <p className="lede" style={{ margin: "6px 0 0" }}>
          {error}. Role holders will appear once <code>GET /api/swarm/roles</code> is live.
        </p>
      </div>
    )
  }
  if (loading && !roles) {
    return (
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ marginBottom: 12 }}>Roles</h2>
        <p className="lede">Loading roles…</p>
      </div>
    )
  }
  if (!roles) return null
  return (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ marginBottom: 12 }}>Roles</h2>
      <div className="grid cards">
        <RoleCard title="Orchestrator" holder={roles.orchestrator} />
        <RoleCard title="Leader" holder={roles.leader} />
      </div>
    </div>
  )
}

function formatRoleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1)
}

function RolePoliciesSection({
  nodeId,
  onRolesRefresh,
}: {
  nodeId: string
  onRolesRefresh: () => Promise<void>
}) {
  const [policies, setPolicies] = useState<SwarmRolePolicy[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const loadPolicies = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await getNodeRolePolicies(nodeId)
      setPolicies(data.policies || [])
    } catch (err) {
      setPolicies([])
      setLoadError(err instanceof Error ? err.message : "Failed to load role policies")
    } finally {
      setLoading(false)
    }
  }, [nodeId])

  useEffect(() => {
    loadPolicies()
  }, [loadPolicies])

  async function handlePolicyChange(role: string, policy: string) {
    setSaving(true)
    setSaveError(null)
    try {
      await putNodeRolePolicy(nodeId, role, policy)
      await loadPolicies()
      await onRolesRefresh()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to update role policy")
    } finally {
      setSaving(false)
    }
  }

  const policyByRole = new Map(policies.map((entry) => [entry.role, entry.policy]))

  return (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ marginTop: 0 }}>Role policies</h2>
      {loadError && (
        <p className="lede" style={{ margin: "0 0 10px", color: "var(--bad)" }}>
          {loadError}
        </p>
      )}
      {saveError && (
        <p className="lede" style={{ margin: "0 0 10px", color: "var(--bad)" }}>
          {saveError}
        </p>
      )}
      {loading && !policies.length && !loadError ? (
        <p className="lede">Loading role policies…</p>
      ) : (
        <div className="grid" style={{ gap: 10 }}>
          {SWARM_ROLE_NAMES.map((role) => (
            <label key={role} className="row" style={{ alignItems: "center", gap: 12 }}>
              <span style={{ minWidth: 110 }}>{formatRoleLabel(role)}</span>
              <select
                value={policyByRole.get(role) ?? "AUTO"}
                disabled={loading || saving}
                onChange={(e) => handlePolicyChange(role, e.target.value)}
              >
                {SWARM_ROLE_POLICY_LEVELS.map((level) => (
                  <option key={level} value={level}>{level}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

function WorkersSection({ workers }: { workers: SwarmWorker[] | undefined }) {
  if (!workers?.length) {
    return <p className="lede">No workers bound to this node.</p>
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Kind</th>
          <th>Status</th>
          <th>ID</th>
          <th>Node ID</th>
        </tr>
      </thead>
      <tbody>
        {workers.map((worker) => (
          <tr key={worker.id}>
            <td><strong>{worker.name}</strong></td>
            <td>{worker.kind}</td>
            <td><span className={`badge ${workerStatusBadgeClass(worker.status)}`}>{worker.status}</span></td>
            <td className="stat">{worker.id}</td>
            <td className="stat">{worker.node_id}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function BudgetSection({
  nodeId,
  refreshKey = 0,
}: {
  nodeId: string
  refreshKey?: number
}) {
  const [budget, setBudget] = useState<SwarmNodeBudget | null>(null)
  const [preset, setPreset] = useState("")
  const [globalPercent, setGlobalPercent] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const loadBudget = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await getNodeBudget(nodeId)
      setBudget(data)
      setPreset(data.preset)
      setGlobalPercent(String(data.global_percent))
    } catch (err) {
      setBudget(null)
      setLoadError(err instanceof Error ? err.message : "Failed to load budget")
    } finally {
      setLoading(false)
    }
  }, [nodeId])

  useEffect(() => {
    loadBudget()
  }, [loadBudget, refreshKey])

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    try {
      const body: SwarmBudgetUpdate = { preset: preset as SwarmBudgetUpdate["preset"] }
      if (preset === "custom") {
        const percent = Number(globalPercent)
        if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
          throw new Error("Custom preset requires global_percent between 0 and 100")
        }
        body.global_percent = percent
      }
      const updated = await putNodeBudget(nodeId, body)
      setBudget(updated)
      setPreset(updated.preset)
      setGlobalPercent(String(updated.global_percent))
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save budget")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ marginTop: 0 }}>Budget</h2>
      {loadError && (
        <p className="lede" style={{ margin: "0 0 10px", color: "var(--bad)" }}>
          {loadError}
        </p>
      )}
      {saveError && (
        <p className="lede" style={{ margin: "0 0 10px", color: "var(--bad)" }}>
          {saveError}
        </p>
      )}
      {loading && !budget && !loadError ? (
        <p className="lede">Loading budget…</p>
      ) : budget ? (
        <>
          <div className="kv" style={{ marginBottom: 12 }}>
            <b>Preset</b><span>{budget.preset}</span>
            <b>Mode</b><span>{budget.mode}</span>
            <b>Global %</b><span>{budget.global_percent}</span>
            <b>Effective</b><span>{formatResourceAmounts(budget.effective)}</span>
            <b>Remaining</b><span>{formatResourceAmounts(budget.remaining)}</span>
            <b>Updated</b><span>{formatTimestamp(budget.updated_at)}</span>
          </div>
          <div className="grid" style={{ gap: 10, maxWidth: 420 }}>
            <label className="row" style={{ alignItems: "center", gap: 12 }}>
              <span style={{ minWidth: 110 }}>Preset</span>
              <select
                value={preset}
                disabled={loading || saving}
                onChange={(e) => setPreset(e.target.value)}
              >
                {SWARM_BUDGET_PRESETS.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
            {preset === "custom" && (
              <label className="row" style={{ alignItems: "center", gap: 12 }}>
                <span style={{ minWidth: 110 }}>Global %</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={globalPercent}
                  disabled={loading || saving}
                  onChange={(e) => setGlobalPercent(e.target.value)}
                />
              </label>
            )}
            <div className="row" style={{ gap: 8 }}>
              <button
                className="btn secondary"
                type="button"
                disabled={loading || saving}
                onClick={handleSave}
              >
                {saving ? "Saving…" : "Save budget"}
              </button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}

function LeasesSection({
  nodeId,
  onLeaseChange,
}: {
  nodeId: string
  onLeaseChange?: () => Promise<void>
}) {
  const [leases, setLeases] = useState<SwarmLease[]>([])
  const [cpuThreads, setCpuThreads] = useState("")
  const [ramGb, setRamGb] = useState("")
  const [ttlSeconds, setTtlSeconds] = useState("300")
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [releasingId, setReleasingId] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const loadLeases = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await listNodeLeases(nodeId)
      setLeases(data.leases || [])
    } catch (err) {
      setLeases([])
      setLoadError(err instanceof Error ? err.message : "Failed to load leases")
    } finally {
      setLoading(false)
    }
  }, [nodeId])

  useEffect(() => {
    loadLeases()
  }, [loadLeases])

  async function handleCreate() {
    setCreating(true)
    setActionError(null)
    try {
      const claim: { cpu_threads?: number; ram_gb?: number } = {}
      if (cpuThreads.trim()) {
        const value = Number(cpuThreads)
        if (!Number.isFinite(value) || value <= 0) {
          throw new Error("cpu_threads must be a positive number")
        }
        claim.cpu_threads = value
      }
      if (ramGb.trim()) {
        const value = Number(ramGb)
        if (!Number.isFinite(value) || value <= 0) {
          throw new Error("ram_gb must be a positive number")
        }
        claim.ram_gb = value
      }
      if (!Object.keys(claim).length) {
        throw new Error("Enter at least one claim value (cpu_threads or ram_gb)")
      }
      const ttl = ttlSeconds.trim() ? Number(ttlSeconds) : 300
      if (!Number.isFinite(ttl) || ttl <= 0) {
        throw new Error("ttl_seconds must be a positive number")
      }
      await createNodeLease(nodeId, { claim, ttl_seconds: ttl })
      setCpuThreads("")
      setRamGb("")
      await loadLeases()
      await onLeaseChange?.()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to create lease")
    } finally {
      setCreating(false)
    }
  }

  async function handleRelease(leaseId: string) {
    setReleasingId(leaseId)
    setActionError(null)
    try {
      await releaseNodeLease(nodeId, leaseId)
      await loadLeases()
      await onLeaseChange?.()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to release lease")
    } finally {
      setReleasingId(null)
    }
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ marginTop: 0 }}>Leases</h2>
      {loadError && (
        <p className="lede" style={{ margin: "0 0 10px", color: "var(--bad)" }}>
          {loadError}
        </p>
      )}
      {actionError && (
        <p className="lede" style={{ margin: "0 0 10px", color: "var(--bad)" }}>
          {actionError}
        </p>
      )}
      {loading && !leases.length && !loadError ? (
        <p className="lede">Loading leases…</p>
      ) : leases.length === 0 ? (
        <p className="lede" style={{ marginBottom: 12 }}>No leases yet.</p>
      ) : (
        <table style={{ marginBottom: 12 }}>
          <thead>
            <tr>
              <th>Status</th>
              <th>Claim</th>
              <th>Created</th>
              <th>Expires</th>
              <th>Released</th>
              <th>ID</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {leases.map((lease) => (
              <tr key={lease.id}>
                <td>
                  <span className={`badge ${leaseStatusBadgeClass(lease.status)}`}>{lease.status}</span>
                </td>
                <td>{formatLeaseClaim(lease.claim)}</td>
                <td className="stat">{formatTimestamp(lease.created_at)}</td>
                <td className="stat">{formatTimestamp(lease.expires_at)}</td>
                <td className="stat">{formatTimestamp(lease.released_at)}</td>
                <td className="stat">{lease.id}</td>
                <td>
                  {lease.status === "active" && (
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={releasingId === lease.id || creating}
                      onClick={() => handleRelease(lease.id)}
                    >
                      {releasingId === lease.id ? "Releasing…" : "Release"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="grid" style={{ gap: 10, maxWidth: 520 }}>
        <h3 style={{ margin: "4px 0 0", fontSize: "0.95rem" }}>Create lease</h3>
        <label className="row" style={{ alignItems: "center", gap: 12 }}>
          <span style={{ minWidth: 110 }}>CPU threads</span>
          <input
            type="number"
            min={1}
            value={cpuThreads}
            disabled={creating || releasingId != null}
            onChange={(e) => setCpuThreads(e.target.value)}
            placeholder="optional"
          />
        </label>
        <label className="row" style={{ alignItems: "center", gap: 12 }}>
          <span style={{ minWidth: 110 }}>RAM (GB)</span>
          <input
            type="number"
            min={0.1}
            step={0.1}
            value={ramGb}
            disabled={creating || releasingId != null}
            onChange={(e) => setRamGb(e.target.value)}
            placeholder="optional"
          />
        </label>
        <label className="row" style={{ alignItems: "center", gap: 12 }}>
          <span style={{ minWidth: 110 }}>TTL (seconds)</span>
          <input
            type="number"
            min={1}
            value={ttlSeconds}
            disabled={creating || releasingId != null}
            onChange={(e) => setTtlSeconds(e.target.value)}
          />
        </label>
        <div className="row" style={{ gap: 8 }}>
          <button
            className="btn secondary"
            type="button"
            disabled={creating || releasingId != null || loading}
            onClick={handleCreate}
          >
            {creating ? "Creating…" : "Create lease"}
          </button>
        </div>
      </div>
    </div>
  )
}

function NodeDetail({
  node,
  onRolesRefresh,
}: {
  node: SwarmNode
  onRolesRefresh: () => Promise<void>
}) {
  const [budgetRefresh, setBudgetRefresh] = useState(0)

  return (
    <div className="card">
      <h2>{node.host_alias}</h2>
      <p className="lede" style={{ margin: "0 0 14px" }}>
        {node.is_local ? "Local node" : "Remote node"} · {node.address}
      </p>
      <RolePoliciesSection nodeId={node.id} onRolesRefresh={onRolesRefresh} />
      <BudgetSection nodeId={node.id} refreshKey={budgetRefresh} />
      <LeasesSection
        nodeId={node.id}
        onLeaseChange={async () => { setBudgetRefresh((key) => key + 1) }}
      />
      <div className="kv" style={{ marginBottom: 16 }}>
        <b>ID</b><span className="stat">{node.id}</span>
        <b>Hostname</b><span>{node.hostname || "—"}</span>
        <b>Host alias</b><span>{node.host_alias}</span>
        <b>Address</b><span>{node.address}</span>
        <b>Status</b><span><span className={`badge ${statusBadgeClass(node.status)}`}>{node.status}</span></span>
        <b>Class</b><span>{node.class}</span>
        <b>Roles</b><span>{formatRoles(node.roles)}</span>
        <b>Local</b><span>{node.is_local ? "yes" : "no"}</span>
        <b>Last seen</b><span>{formatTimestamp(node.last_seen_at)}</span>
        <b>Updated</b><span>{formatTimestamp(node.updated_at)}</span>
      </div>
      <h2 style={{ marginTop: 0 }}>Workers</h2>
      <WorkersSection workers={node.workers} />
      <h2 style={{ marginTop: 18 }}>Resources</h2>
      <p className="lede" style={{ margin: "0 0 10px" }}>{formatResources(node.resources)}</p>
      <ObjectKv data={node.resources as Record<string, unknown>} />
      <h2 style={{ marginTop: 18 }}>Hardware</h2>
      <p className="lede" style={{ margin: "0 0 10px" }}>{formatHardware(node.hardware)}</p>
      <ObjectKv data={node.hardware as Record<string, unknown>} />
    </div>
  )
}

export function SwarmPage() {
  const { nodeId } = useParams()
  const navigate = useNavigate()
  const [nodes, setNodes] = useState<SwarmNode[]>([])
  const [roles, setRoles] = useState<SwarmRolesResponse | null>(null)
  const [selected, setSelected] = useState<SwarmNode | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [rolesError, setRolesError] = useState<string | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshList = useCallback(async () => {
    try {
      const data = await listSwarmNodes()
      setNodes(data.nodes || [])
      setListError(null)
    } catch (err) {
      setNodes([])
      setListError(err instanceof Error ? err.message : "Failed to load swarm nodes")
    }
  }, [])

  const refreshRoles = useCallback(async () => {
    try {
      const data = await listSwarmRoles()
      setRoles(data)
      setRolesError(null)
    } catch (err) {
      setRoles(null)
      setRolesError(err instanceof Error ? err.message : "Failed to load swarm roles")
    }
  }, [])

  const loadDetail = useCallback(async (id: string) => {
    setDetailError(null)
    try {
      const node = await getSwarmNode(id)
      setSelected(node)
    } catch (err) {
      setSelected(null)
      setDetailError(err instanceof Error ? err.message : "Failed to load node detail")
    }
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([refreshList(), refreshRoles()]).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [refreshList, refreshRoles])

  useEffect(() => {
    if (!nodeId) {
      setSelected(null)
      setDetailError(null)
      return
    }
    loadDetail(nodeId)
  }, [nodeId, loadDetail])

  async function handleRefresh() {
    setLoading(true)
    await Promise.all([refreshList(), refreshRoles()])
    if (nodeId) await loadDetail(nodeId)
    setLoading(false)
  }

  return (
    <div>
      <h1>Swarm</h1>
      <p className="lede">
        Registered nodes in the Jarvis swarm. The local machine appears as <code>localhost</code> until remote pairing ships in P3.
      </p>
      <div className="row" style={{ marginBottom: 16 }}>
        <button className="btn secondary" type="button" onClick={handleRefresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
        {nodeId && (
          <button className="btn secondary" type="button" onClick={() => navigate("/swarm")}>
            Clear selection
          </button>
        )}
      </div>
      <RolesSection roles={roles} error={rolesError} loading={loading} />
      <PlacementSection
        onPlaced={async () => {
          await refreshList()
          if (nodeId) await loadDetail(nodeId)
        }}
      />
      {listError && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--warn)", padding: "12px 16px" }}>
          <strong>Nodes API unavailable</strong>
          <p className="lede" style={{ margin: "6px 0 0" }}>
            {listError}. The swarm identity API may not be merged yet; this page will populate once <code>GET /api/swarm/nodes</code> is live.
          </p>
        </div>
      )}
      <div className="grid two">
        <div className="card">
          <h2>Nodes</h2>
          {loading && !nodes.length && !listError ? (
            <p className="lede">Loading nodes…</p>
          ) : nodes.length === 0 ? (
            <p className="lede">No nodes registered yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Alias</th>
                  <th>Status</th>
                  <th>Class</th>
                  <th>Roles</th>
                  <th>Workers</th>
                  <th>Resources</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((node) => (
                  <tr
                    key={node.id}
                    className={nodeId === node.id ? "swarm-row selected" : "swarm-row"}
                    onClick={() => navigate(`/swarm/${node.id}`)}
                  >
                    <td>
                      <Link to={`/swarm/${node.id}`} onClick={(e) => e.stopPropagation()}>
                        <strong>{node.host_alias}</strong>
                        {node.is_local && <span className="stat" style={{ marginLeft: 8 }}>local</span>}
                      </Link>
                      <div className="stat" style={{ marginTop: 4 }}>{node.address}</div>
                    </td>
                    <td><span className={`badge ${statusBadgeClass(node.status)}`}>{node.status}</span></td>
                    <td>{node.class}</td>
                    <td>{formatRoles(node.roles)}</td>
                    <td className="stat">{node.workers?.length ?? 0}</td>
                    <td className="stat">{formatResources(node.resources)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div>
          {nodeId && detailError && (
            <div className="card" style={{ borderLeft: "4px solid var(--bad)", padding: "12px 16px" }}>
              <strong>Node detail unavailable</strong>
              <p className="lede" style={{ margin: "6px 0 0" }}>{detailError}</p>
            </div>
          )}
          {selected && <NodeDetail node={selected} onRolesRefresh={refreshRoles} />}
          {!nodeId && !listError && nodes.length > 0 && (
            <div className="card">
              <h2>Node detail</h2>
              <p className="lede">Select a node to load detail from <code>GET /api/swarm/nodes/&lt;id&gt;</code>.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
