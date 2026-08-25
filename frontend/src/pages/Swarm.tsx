import { Fragment, useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  getSwarmNode,
  listSwarmNodes,
  type SwarmNode,
  type SwarmNodeHardware,
  type SwarmNodeResources,
} from "../api"

function statusBadgeClass(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === "online") return "completed"
  if (normalized === "offline") return "failed"
  return "queued"
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

function NodeDetail({ node }: { node: SwarmNode }) {
  return (
    <div className="card">
      <h2>{node.host_alias}</h2>
      <p className="lede" style={{ margin: "0 0 14px" }}>
        {node.is_local ? "Local node" : "Remote node"} · {node.address}
      </p>
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
      <h2 style={{ marginTop: 0 }}>Resources</h2>
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
  const [selected, setSelected] = useState<SwarmNode | null>(null)
  const [listError, setListError] = useState<string | null>(null)
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
    refreshList().finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [refreshList])

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
    await refreshList()
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
          {selected && <NodeDetail node={selected} />}
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
