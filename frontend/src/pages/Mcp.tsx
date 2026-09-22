import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../api"
import { IntegrationSetup } from "../components/IntegrationSetup"

type McpServer = {
  id?: string
  name: string
  transport?: string
  command?: string
  url?: string
  status?: string
  tools?: string[]
  error?: string
  agent_exposed?: boolean
  enabled?: boolean
}

type Usability = {
  mcp?: McpServer[]
  vault?: { bound?: boolean; note_count?: number }
  supermemory?: { healthy?: boolean; installed?: boolean; running?: boolean; enabled?: boolean; install_status?: string }
  workers?: { id: string; name: string; status: string; available?: boolean }[]
  agent_mcp_tools?: string[]
}

export function McpPage() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [jarvis, setJarvis] = useState<any>(null)
  const [usability, setUsability] = useState<Usability | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [name, setName] = useState("filesystem")
  const [transport, setTransport] = useState("stdio")
  const [command, setCommand] = useState("npx")
  const [args, setArgs] = useState("-y @modelcontextprotocol/server-filesystem C:/Users/daanv/Desktop")
  const [url, setUrl] = useState("")

  async function refresh(probe = false) {
    if (probe) {
      setRefreshing(true)
      await api("/api/mcp/refresh", { method: "POST" }).catch(() => null)
    }
    const [list, builtin, hub] = await Promise.all([
      api<McpServer[]>("/api/mcp"),
      api("/api/mcp/jarvis").catch(() => null),
      api<Usability>("/api/mcp/usability").catch(() => null),
    ])
    setServers(list)
    setJarvis(builtin)
    setUsability(hub)
    setRefreshing(false)
  }
  useEffect(() => { void refresh(true) }, [])

  return (
    <div>
      <h1>Connections</h1>
      <p className="lede">Connect the services Jarvis can use. You should not need a terminal for normal setup.</p>
      <IntegrationSetup onReady={() => void refresh(true)} />

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>MCP servers</h2>
          <button className="btn secondary" disabled={refreshing} onClick={() => void refresh(true)}>
            {refreshing ? "Refreshing…" : "Refresh tools"}
          </button>
        </div>
        <p className="lede">
          Connected tools are sent to the agent automatically. {usability?.agent_mcp_tools?.length
            ? `Currently exposed: ${usability.agent_mcp_tools.join(", ")}.`
            : "No MCP tools are attached until a server lists tools."}
        </p>
        {servers.map((server) => (
          <div className="toggle" key={server.id || server.name}>
            <div>
              <strong>{server.name}</strong>
              <div className="lede" style={{ margin: 0 }}>
                {server.transport} {server.command || server.url} · {server.status || "not probed"}
                {server.agent_exposed ? " · attached to agent" : ""}
              </div>
              {!!server.tools?.length && (
                <div className="lede" style={{ margin: 0 }}>Tools: {server.tools.join(", ")}</div>
              )}
              {server.error ? <div className="lede" style={{ margin: 0 }}>{server.error}</div> : null}
            </div>
            <button className="btn secondary" onClick={async () => {
              await api(`/api/mcp/${server.id}`, { method: "DELETE" })
              void refresh()
            }}>Remove</button>
          </div>
        ))}
        {!servers.length && <p className="lede">No MCP servers yet. Connect Gmail or WhatsApp above, or add a custom server.</p>}
      </div>

      <div className="grid two" style={{ marginBottom: 16 }}>
        <div className="card">
          <h2>Obsidian vault</h2>
          <p className="lede">
            {usability?.vault?.bound
              ? `Bound · ${usability.vault.note_count ?? 0} notes indexed. Agent tool: vault_memory.`
              : "Not bound. Bind a folder in Settings → Integrations."}
          </p>
          <div className="row">
            <Link className="btn secondary" to="/settings/integrations">Vault settings</Link>
            <Link className="btn secondary" to="/obsidian">Open Obsidian pane</Link>
          </div>
        </div>
        <div className="card">
          <h2>Supermemory</h2>
          <p className="lede">
            {usability?.supermemory
              ? `${usability.supermemory.healthy ? "healthy" : usability.supermemory.running ? "running" : usability.supermemory.installed ? "installed" : "not installed"}${usability.supermemory.enabled ? " · recall enabled" : " · native memory only"}`
              : "Status unavailable."}
          </p>
          <Link className="btn secondary" to="/memory">Open Memory</Link>
        </div>
      </div>

      {!!usability?.workers?.length && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Optional workers</h2>
          <p className="lede">Pinned sidecars Jarvis can start. They are not git-vendored; install from Memory / catalog when you need them.</p>
          {usability.workers.map((worker) => (
            <div className="toggle" key={worker.id}>
              <div>
                <strong>{worker.name}</strong>
                <div className="lede" style={{ margin: 0 }}>{worker.status || "unknown"}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      <details className="advanced-connections">
        <summary>Advanced MCP settings</summary>
        <p className="lede">For custom local tools and developer integrations.</p>
        {jarvis && (
          <div className="card" style={{ marginBottom: 16 }}>
            <h2>Jarvis MCP for Cursor</h2>
            <p className="lede">Cursor attaches as a client while Jarvis stays the supervisor.</p>
            <div className="lede" style={{ margin: "8px 0" }}><code>{jarvis.command}</code></div>
            <div className="lede">Read: {(jarvis.read_tools || []).join(", ")}</div>
            <div className="lede">Report: {(jarvis.action_tools || []).join(", ")}</div>
          </div>
        )}
        <div className="grid two">
          <div className="card">
            <h2>Add server</h2>
            <div className="grid" style={{ gap: 10 }}>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="name" />
              <select value={transport} onChange={(e) => setTransport(e.target.value)}>
                <option value="stdio">stdio</option>
                <option value="http">http</option>
              </select>
              {transport === "stdio" ? (
                <>
                  <input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="command" />
                  <input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="args" />
                </>
              ) : (
                <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:3000" />
              )}
              <button className="btn" onClick={async () => {
                await api("/api/mcp", {
                  method: "POST",
                  body: JSON.stringify({ name, transport, command, args: args.split(" ").filter(Boolean), url, enabled: true }),
                })
                void refresh()
              }}>Add MCP server</button>
            </div>
          </div>
        </div>
      </details>
    </div>
  )
}
