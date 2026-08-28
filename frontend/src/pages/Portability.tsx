import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  createPortableAgent,
  emptyPortableAgentState,
  formatPortabilityError,
  getPortableAgent,
  leasePortableAgent,
  listPortableAgentAudit,
  listPortableAgents,
  listRuntimeProfiles,
  listSwarmNodes,
  migratePortableAgent,
  releasePortableAgentLease,
  resumePortableAgent,
  suspendPortableAgent,
  updatePortableAgentState,
  type AgentRuntimeLease,
  type PortableAgent,
  type PortableAgentState,
  type PortabilityAuditEvent,
  type RuntimeProfile,
  type SwarmNode,
} from "../api"

const STATUS_COPY: Record<string, string> = {
  idle: "Idle",
  running: "Leased",
  suspended: "Suspended",
}

const EVENT_COPY: Record<string, string> = {
  created: "Created",
  lease_acquired: "Runtime leased",
  lease_released: "Lease released",
  migrated: "Moved to another runtime",
  suspended: "Suspended",
  resumed: "Resumed",
  state_updated: "Portable state saved",
}

function statusLabel(status: string): string {
  return STATUS_COPY[status] || status
}

function statusBadgeClass(status: string): string {
  const key = status.toLowerCase()
  if (key === "running") return "running"
  if (key === "suspended") return "queued"
  if (key === "idle") return "completed"
  return "queued"
}

function leaseBadgeClass(status: string): string {
  const key = status.toLowerCase()
  if (key === "active") return "running"
  if (key === "released") return "completed"
  return "queued"
}

function eventLabel(event: string): string {
  return EVENT_COPY[event] || event.replaceAll("_", " ")
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function parseTags(value: string): string[] {
  return value
    .split(/[,;\n]/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function tagsToInput(value: string[] | undefined): string {
  return (value || []).join(", ")
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return "{}"
  }
}

function parseJsonObject(raw: string, label: string): Record<string, unknown> {
  const trimmed = raw.trim()
  if (!trimmed) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error(`${label} must be valid JSON.`)
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`)
  }
  return parsed as Record<string, unknown>
}

function parseJsonObjectList(raw: string, label: string): Record<string, unknown>[] {
  const trimmed = raw.trim()
  if (!trimmed) return []
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error(`${label} must be valid JSON.`)
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON array.`)
  }
  return parsed.map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new Error(`${label} item ${index + 1} must be a JSON object.`)
    }
    return item as Record<string, unknown>
  })
}

function profileLabel(profile: RuntimeProfile | undefined, id: string): string {
  if (!profile) return id || "—"
  return profile.label || profile.name || id
}

function nodeLabel(node: SwarmNode): string {
  return node.host_alias || node.hostname || node.id
}

function assertStableAgentId(expected: string, actual: string | undefined | null, action: string): void {
  if (actual && actual !== expected) {
    throw new Error(
      `Agent ID changed during ${action} (${expected} → ${actual}). That should not happen. Refusing to continue.`,
    )
  }
}

function activeLeaseOf(agent: PortableAgent | null): AgentRuntimeLease | null {
  if (!agent) return null
  return agent.active_lease || agent.lease || null
}

type StateForm = {
  memory: string
  task_state: string
  skill_refs: string
  goals: string
  required_tools: string
  required_capabilities: string
}

function formFromState(state: PortableAgentState): StateForm {
  return {
    memory: prettyJson(state.memory),
    task_state: prettyJson(state.task_state),
    skill_refs: tagsToInput(state.skill_refs),
    goals: prettyJson(state.goals),
    required_tools: tagsToInput(state.required_tools),
    required_capabilities: tagsToInput(state.required_capabilities),
  }
}

export function PortabilityPage() {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const [agents, setAgents] = useState<PortableAgent[]>([])
  const [detail, setDetail] = useState<PortableAgent | null>(null)
  const [audit, setAudit] = useState<PortabilityAuditEvent[]>([])
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([])
  const [nodes, setNodes] = useState<SwarmNode[]>([])
  const [name, setName] = useState("")
  const [createCaps, setCreateCaps] = useState("llm_inference, text")
  const [createTools, setCreateTools] = useState("")
  const [createNotes, setCreateNotes] = useState("")
  const [runtimeId, setRuntimeId] = useState("")
  const [nodeId, setNodeId] = useState("localhost")
  const [stateForm, setStateForm] = useState<StateForm>(formFromState(emptyPortableAgentState()))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")
  const [copied, setCopied] = useState(false)
  const [detailReady, setDetailReady] = useState(false)

  const selectedId = agentId || ""
  const lease = activeLeaseOf(detail)
  const state = detail?.state || emptyPortableAgentState()

  const profileById = useMemo(() => {
    const map = new Map<string, RuntimeProfile>()
    for (const profile of profiles) {
      map.set(profile.id, profile)
      if (profile.name) map.set(profile.name, profile)
    }
    return map
  }, [profiles])

  const refreshList = useCallback(async () => {
    const data = await listPortableAgents()
    setAgents(data.agents || [])
  }, [])

  const refreshDetail = useCallback(async (id: string) => {
    const [agent, events] = await Promise.all([
      getPortableAgent(id),
      listPortableAgentAudit({ agentId: id, limit: 50 }).catch(() => ({
        events: [] as PortabilityAuditEvent[],
      })),
    ])
    assertStableAgentId(id, agent.id, "load")
    setDetail(agent)
    setAudit(events.events || [])
    return agent
  }, [])

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        await refreshList()
      } catch (err: unknown) {
        if (!cancelled) setError(formatPortabilityError(err))
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
    listRuntimeProfiles()
      .then((data) => {
        const items = data.profiles || []
        setProfiles(items)
        setRuntimeId((current) => current || items[0]?.id || "")
      })
      .catch(() => undefined)
    listSwarmNodes()
      .then((data) => setNodes(data.nodes || []))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    setCopied(false)
    if (!selectedId) {
      setDetail(null)
      setAudit([])
      setDetailReady(false)
      return
    }
    let cancelled = false
    setDetailReady(false)
    const load = async (initial: boolean) => {
      try {
        const agent = await refreshDetail(selectedId)
        if (cancelled) return
        if (initial) {
          setStateForm(formFromState(agent.state || emptyPortableAgentState()))
          const currentLease = activeLeaseOf(agent)
          if (currentLease?.runtime_profile_id) setRuntimeId(currentLease.runtime_profile_id)
          if (currentLease?.node_id) setNodeId(currentLease.node_id)
          setError("")
        }
        setDetailReady(true)
      } catch (err: unknown) {
        if (!cancelled) {
          setDetail(null)
          setDetailReady(true)
          setError(formatPortabilityError(err))
        }
      }
    }
    void load(true)
    const id = window.setInterval(() => void load(false), 8000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [selectedId, refreshDetail])

  function stableIdMessage(id: string, action: string): string {
    return `${action} Agent ID is still ${id}. Runtime and node are a lease, not a new identity.`
  }

  async function confirmAndReload(id: string, action: string): Promise<PortableAgent> {
    const fresh = await refreshDetail(id)
    assertStableAgentId(id, fresh.id, action)
    setStateForm(formFromState(fresh.state || emptyPortableAgentState()))
    await refreshList()
    return fresh
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError("Give this agent a name.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const notes = createNotes.trim()
      const created = await createPortableAgent({
        name: trimmed,
        memory: notes ? { notes } : {},
        required_capabilities: parseTags(createCaps),
        required_tools: parseTags(createTools),
      })
      setName("")
      setCreateNotes("")
      setMsg(
        `Created ${created.name}. Agent ID ${created.id} stays the same if you lease, migrate, suspend, or resume.`,
      )
      await refreshList()
      navigate(`/portability/${created.id}`)
    } catch (err: unknown) {
      setError(formatPortabilityError(err))
    } finally {
      setBusy(false)
    }
  }

  function requireRuntime(): string | null {
    if (!runtimeId) {
      setError("Pick a runtime. Runtimes are defined under Model.")
      return null
    }
    return runtimeId
  }

  async function onLease() {
    if (!selectedId) return
    const runtime = requireRuntime()
    if (!runtime) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const leased = await leasePortableAgent(selectedId, {
        runtime_profile_id: runtime,
        node_id: nodeId.trim() || "localhost",
      })
      assertStableAgentId(selectedId, leased.agent_id, "lease")
      await confirmAndReload(selectedId, "lease")
      setMsg(stableIdMessage(selectedId, "Runtime leased."))
    } catch (err: unknown) {
      setError(formatPortabilityError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onMigrate() {
    if (!selectedId) return
    const runtime = requireRuntime()
    if (!runtime) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const migrated = await migratePortableAgent(selectedId, {
        target_runtime_profile_id: runtime,
        node_id: nodeId.trim() || "localhost",
      })
      assertStableAgentId(selectedId, migrated.id, "migrate")
      if (migrated.lease) assertStableAgentId(selectedId, migrated.lease.agent_id, "migrate")
      await confirmAndReload(selectedId, "migrate")
      setMsg(stableIdMessage(selectedId, "Lease moved to another runtime."))
    } catch (err: unknown) {
      setError(formatPortabilityError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onSuspend() {
    if (!selectedId) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const suspended = await suspendPortableAgent(selectedId)
      assertStableAgentId(selectedId, suspended.id, "suspend")
      await confirmAndReload(selectedId, "suspend")
      setMsg(stableIdMessage(selectedId, "Agent suspended. Memory and policy are still on this Agent ID."))
    } catch (err: unknown) {
      setError(formatPortabilityError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onResume() {
    if (!selectedId) return
    const runtime = requireRuntime()
    if (!runtime) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const resumed = await resumePortableAgent(selectedId, {
        runtime_profile_id: runtime,
        node_id: nodeId.trim() || "localhost",
      })
      assertStableAgentId(selectedId, resumed.id, "resume")
      if (resumed.lease) assertStableAgentId(selectedId, resumed.lease.agent_id, "resume")
      await confirmAndReload(selectedId, "resume")
      setMsg(stableIdMessage(selectedId, "Agent resumed."))
    } catch (err: unknown) {
      setError(formatPortabilityError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onRelease() {
    if (!lease?.id || !selectedId) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const released = await releasePortableAgentLease(lease.id)
      assertStableAgentId(selectedId, released.agent_id, "release")
      await confirmAndReload(selectedId, "release")
      setMsg(stableIdMessage(selectedId, "Lease released."))
    } catch (err: unknown) {
      setError(formatPortabilityError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onSaveState(event: FormEvent) {
    event.preventDefault()
    if (!selectedId) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const updated = await updatePortableAgentState(selectedId, {
        memory: parseJsonObject(stateForm.memory, "Memory"),
        task_state: parseJsonObject(stateForm.task_state, "Task state"),
        skill_refs: parseTags(stateForm.skill_refs),
        goals: parseJsonObjectList(stateForm.goals, "Goals"),
        required_tools: parseTags(stateForm.required_tools),
        required_capabilities: parseTags(stateForm.required_capabilities),
      })
      assertStableAgentId(selectedId, updated.id, "save state")
      await confirmAndReload(selectedId, "save state")
      setMsg(stableIdMessage(selectedId, "Portable state saved. Policy and authority were not changed."))
    } catch (err: unknown) {
      setError(formatPortabilityError(err))
    } finally {
      setBusy(false)
    }
  }

  async function copyAgentId() {
    if (!detail?.id) return
    try {
      await navigator.clipboard.writeText(detail.id)
      setCopied(true)
    } catch {
      setCopied(false)
      setError("Could not copy the Agent ID.")
    }
  }

  const hasLease = Boolean(lease && lease.status === "active")
  const canResume = detail ? detail.status === "suspended" || detail.status === "idle" : false
  const canLease = detail ? !hasLease : false

  return (
    <div className="portability-page">
      <h1>Portability</h1>
      <p className="lede">
        The Agent ID is who this specialist is. A runtime and a node are a temporary lease, not a new
        agent. Memory, policy, skills, goals, and task state stay with that ID when you lease, migrate,
        suspend, or resume. Moving a lease does not dump a live process or GPU memory. To change what
        an agent may do, use the{" "}
        <Link to="/agents">Agents interview</Link> — this page does not raise authority.
      </p>

      {error && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--bad)", padding: "12px 16px" }}>
          {error}
        </div>
      )}
      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}

      {selectedId && detail ? (
        <AgentDetail
          agent={detail}
          lease={lease}
          state={state}
          audit={audit}
          profiles={profiles}
          profileById={profileById}
          nodes={nodes}
          runtimeId={runtimeId}
          nodeId={nodeId}
          stateForm={stateForm}
          busy={busy}
          copied={copied}
          hasLease={hasLease}
          canLease={canLease}
          canResume={canResume}
          onRuntime={setRuntimeId}
          onNode={setNodeId}
          onStateForm={setStateForm}
          onCopy={copyAgentId}
          onLease={onLease}
          onMigrate={onMigrate}
          onSuspend={onSuspend}
          onResume={onResume}
          onRelease={onRelease}
          onSaveState={onSaveState}
          error={error}
        />
      ) : selectedId && !detailReady ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <p className="lede" style={{ margin: 0 }}>
            Loading this Agent ID…
          </p>
        </div>
      ) : selectedId && !detail ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <p className="lede" style={{ margin: 0 }}>
            This agent could not be opened. <Link to="/portability">Back to all agents</Link>
          </p>
        </div>
      ) : (
        <form className="card grid" style={{ maxWidth: 760, marginBottom: 16 }} onSubmit={onCreate}>
          <h2>New portable agent</h2>
          <p className="lede" style={{ margin: 0 }}>
            Creates a durable Agent ID. You can attach a runtime later. Authority is not set here.
          </p>
          <label>
            Name
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Researcher"
              aria-label="Agent name"
            />
          </label>
          <label>
            Required capabilities
            <input
              type="text"
              value={createCaps}
              onChange={(event) => setCreateCaps(event.target.value)}
              placeholder="llm_inference, text"
              aria-label="Required capabilities"
            />
          </label>
          <label>
            Required tools
            <input
              type="text"
              value={createTools}
              onChange={(event) => setCreateTools(event.target.value)}
              placeholder="filesystem, browser"
              aria-label="Required tools"
            />
          </label>
          <label>
            Notes (stored in memory, optional)
            <textarea
              className="field"
              rows={3}
              value={createNotes}
              onChange={(event) => setCreateNotes(event.target.value)}
              placeholder="What this specialist is for"
              aria-label="Memory notes"
            />
          </label>
          <div className="row">
            <button className="btn" type="submit" disabled={busy}>
              Create agent
            </button>
          </div>
        </form>
      )}

      <div className="card">
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>{selectedId ? "All portable agents" : "Portable agents"}</span>
          {selectedId && (
            <Link className="btn secondary" to="/portability">
              New agent
            </Link>
          )}
        </div>
        {agents.length === 0 ? (
          <p className="lede" style={{ margin: 0 }}>
            No portable agents yet. Create one to get a stable Agent ID you can move between runtimes.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Agent ID</th>
                <th>Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr
                  key={agent.id}
                  className={`env-row${agent.id === selectedId ? " selected" : ""}`}
                  onClick={() => navigate(`/portability/${agent.id}`)}
                >
                  <td>
                    <strong>{agent.name}</strong>
                  </td>
                  <td>
                    <span className="stat">{agent.id}</span>
                  </td>
                  <td>
                    <span className={`badge ${statusBadgeClass(agent.status)}`}>{statusLabel(agent.status)}</span>
                  </td>
                  <td>{formatWhen(agent.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function AgentDetail({
  agent,
  lease,
  state,
  audit,
  profiles,
  profileById,
  nodes,
  runtimeId,
  nodeId,
  stateForm,
  busy,
  copied,
  hasLease,
  canLease,
  canResume,
  onRuntime,
  onNode,
  onStateForm,
  onCopy,
  onLease,
  onMigrate,
  onSuspend,
  onResume,
  onRelease,
  onSaveState,
  error,
}: {
  agent: PortableAgent
  lease: AgentRuntimeLease | null
  state: PortableAgentState
  audit: PortabilityAuditEvent[]
  profiles: RuntimeProfile[]
  profileById: Map<string, RuntimeProfile>
  nodes: SwarmNode[]
  runtimeId: string
  nodeId: string
  stateForm: StateForm
  busy: boolean
  copied: boolean
  hasLease: boolean
  canLease: boolean
  canResume: boolean
  onRuntime: (value: string) => void
  onNode: (value: string) => void
  onStateForm: (value: StateForm) => void
  onCopy: () => void
  onLease: () => void
  onMigrate: () => void
  onSuspend: () => void
  onResume: () => void
  onRelease: () => void
  onSaveState: (event: FormEvent) => void
  error: string
}) {
  const leaseProfile = lease ? profileById.get(lease.runtime_profile_id) : undefined
  const knownNodeIds = new Set(nodes.map((node) => node.id))

  return (
    <>
      <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--gold)" }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ marginBottom: 4 }}>{agent.name}</h2>
            <span className={`badge ${statusBadgeClass(agent.status)}`}>{statusLabel(agent.status)}</span>
          </div>
          <Link className="btn secondary" to="/portability">
            All agents
          </Link>
        </div>
        <p className="lede" style={{ margin: "12px 0 6px" }}>
          Agent ID — stable across lease, migrate, suspend, and resume
        </p>
        <div className="row">
          <code className="stat" style={{ overflowWrap: "anywhere" }}>
            {agent.id}
          </code>
          <button className="btn secondary" type="button" onClick={onCopy}>
            {copied ? "Copied" : "Copy ID"}
          </button>
        </div>
        <p className="lede" style={{ margin: "12px 0 0" }}>
          Runtime and node below are the current lease. Changing them does not mint a new Agent ID and
          does not move a live GPU process.
        </p>
      </div>

      <div className="grid two" style={{ marginBottom: 16 }}>
        <div className="card">
          <h2>Current lease</h2>
          {lease ? (
            <div className="kv">
              <b>Lease ID</b>
              <span className="stat">{lease.id}</span>
              <b>Status</b>
              <span>
                <span className={`badge ${leaseBadgeClass(lease.status)}`}>{lease.status}</span>
              </span>
              <b>Runtime</b>
              <span>{profileLabel(leaseProfile, lease.runtime_profile_id)}</span>
              <b>Node</b>
              <span>{lease.node_id || "—"}</span>
              <b>Model</b>
              <span>{lease.model || "—"}</span>
              <b>Endpoint</b>
              <span className="stat">{lease.endpoint || "—"}</span>
              <b>Leased</b>
              <span>{formatWhen(lease.created_at)}</span>
            </div>
          ) : (
            <p className="lede" style={{ margin: 0 }}>
              No active lease. This agent still exists. Pick a runtime to lease or resume.
            </p>
          )}
        </div>

        <div className="card">
          <h2>Attach or move a lease</h2>
          {error && (
            <div className="card" style={{ marginBottom: 12, borderLeft: "4px solid var(--bad)", padding: "12px 16px" }} role="alert">
              {error}
            </div>
          )}
          <p className="lede" style={{ margin: "0 0 12px" }}>
            Choose where this same agent should run. Incompatible runtimes are rejected in plain
            language — nothing is silently downgraded.{" "}
            <Link to="/model">Manage runtimes</Link>
          </p>
          <label>
            Runtime
            <select
              value={runtimeId}
              onChange={(event) => onRuntime(event.target.value)}
              aria-label="Runtime profile"
            >
              {!runtimeId && <option value="">Select a runtime</option>}
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.label || profile.name}
                </option>
              ))}
            </select>
          </label>
          <label style={{ marginTop: 12 }}>
            Node
            <select
              value={knownNodeIds.has(nodeId) || nodeId === "localhost" ? nodeId : "__custom"}
              onChange={(event) => {
                const value = event.target.value
                if (value === "__custom") return
                onNode(value)
              }}
              aria-label="Node"
            >
              <option value="localhost">localhost</option>
              {nodes.map((node) => (
                <option key={node.id} value={node.id}>
                  {nodeLabel(node)}
                </option>
              ))}
              {!knownNodeIds.has(nodeId) && nodeId !== "localhost" && (
                <option value="__custom">{nodeId}</option>
              )}
            </select>
          </label>
          <label style={{ marginTop: 12 }}>
            Node id (lease, not identity)
            <input
              type="text"
              value={nodeId}
              onChange={(event) => onNode(event.target.value)}
              placeholder="localhost"
              aria-label="Node id"
            />
          </label>
          <div className="row" style={{ marginTop: 14 }}>
            {canLease && (
              <button className="btn" type="button" disabled={busy} onClick={onLease}>
                Lease runtime
              </button>
            )}
            <button className="btn secondary" type="button" disabled={busy} onClick={onMigrate}>
              Move lease
            </button>
            {canResume && (
              <button className="btn" type="button" disabled={busy} onClick={onResume}>
                Resume
              </button>
            )}
            <button className="btn secondary" type="button" disabled={busy || agent.status === "suspended"} onClick={onSuspend}>
              Suspend
            </button>
            {hasLease && (
              <button className="btn secondary" type="button" disabled={busy} onClick={onRelease}>
                Release lease
              </button>
            )}
          </div>
        </div>
      </div>

      <form className="card grid" style={{ marginBottom: 16 }} onSubmit={onSaveState}>
        <h2>Portable state</h2>
        <p className="lede" style={{ margin: 0 }}>
          Saved with the Agent ID, not with the runtime. Saving here does not change policy or raise
          authority.
        </p>
        <div className="grid two">
          <label>
            Memory (JSON)
            <textarea
              className="field"
              rows={8}
              value={stateForm.memory}
              onChange={(event) => onStateForm({ ...stateForm, memory: event.target.value })}
              aria-label="Memory JSON"
            />
          </label>
          <label>
            Task state (JSON)
            <textarea
              className="field"
              rows={8}
              value={stateForm.task_state}
              onChange={(event) => onStateForm({ ...stateForm, task_state: event.target.value })}
              aria-label="Task state JSON"
            />
          </label>
        </div>
        <label>
          Skills
          <input
            type="text"
            value={stateForm.skill_refs}
            onChange={(event) => onStateForm({ ...stateForm, skill_refs: event.target.value })}
            placeholder="skill-1, skill-2"
            aria-label="Skill references"
          />
        </label>
        <label>
          Goals (JSON array)
          <textarea
            className="field"
            rows={4}
            value={stateForm.goals}
            onChange={(event) => onStateForm({ ...stateForm, goals: event.target.value })}
            aria-label="Goals JSON"
          />
        </label>
        <div className="grid two">
          <label>
            Required tools
            <input
              type="text"
              value={stateForm.required_tools}
              onChange={(event) => onStateForm({ ...stateForm, required_tools: event.target.value })}
              placeholder="filesystem, browser"
              aria-label="Required tools"
            />
          </label>
          <label>
            Required capabilities
            <input
              type="text"
              value={stateForm.required_capabilities}
              onChange={(event) =>
                onStateForm({ ...stateForm, required_capabilities: event.target.value })
              }
              placeholder="llm_inference, text"
              aria-label="Required capabilities"
            />
          </label>
        </div>
        <div className="row">
          <button className="btn" type="submit" disabled={busy}>
            Save portable state
          </button>
        </div>
      </form>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Policy (read-only here)</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Authority lives with the{" "}
          <Link to="/agents">Agents interview</Link>. This portal will not raise it.
        </p>
        <pre className="stat" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
          {prettyJson(state.policy)}
        </pre>
      </div>

      {state.provenance.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Provenance</h2>
          {state.provenance.map((item, index) => (
            <div className="suggestion-row" key={`${String(item.event || "event")}-${index}`}>
              <div>
                <strong>{eventLabel(String(item.event || "event"))}</strong>
                <p>{prettyJson(item)}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Executor history</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Which runtime and node actually ran this Agent ID. The ID in every row should match.
        </p>
        {audit.length === 0 ? (
          <p className="lede" style={{ margin: 0 }}>
            No lease history yet.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Event</th>
                <th>Agent ID</th>
                <th>Runtime</th>
                <th>Node</th>
                <th>Model</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((event) => (
                <tr key={event.id}>
                  <td>{formatWhen(event.created_at)}</td>
                  <td>{eventLabel(event.event)}</td>
                  <td>
                    <span className="stat">{event.agent_id}</span>
                  </td>
                  <td>{profileLabel(profileById.get(event.runtime_profile_id), event.runtime_profile_id)}</td>
                  <td>{event.node_id || "—"}</td>
                  <td>{event.model || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
