import { useEffect, useState } from "react"
import { api } from "../api"
import { IntegrationSetup } from "../components/IntegrationSetup"

export function McpPage() {
  const [servers, setServers] = useState<any[]>([])
  const [jarvis, setJarvis] = useState<any>(null)
  const [name, setName] = useState("filesystem")
  const [transport, setTransport] = useState("stdio")
  const [command, setCommand] = useState("npx")
  const [args, setArgs] = useState("-y @modelcontextprotocol/server-filesystem C:/Users/daanv/Desktop")
  const [url, setUrl] = useState("")

  async function refresh() {
    const [list, builtin] = await Promise.all([
      api<any[]>("/api/mcp"),
      api("/api/mcp/jarvis").catch(() => null),
    ])
    setServers(list)
    setJarvis(builtin)
  }
  useEffect(() => { refresh() }, [])

  return (
    <div>
      <h1>Connections</h1>
      <p className="lede">Connect the services Jarvis can use. You should not need a terminal for normal setup.</p>
      <IntegrationSetup />

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
                refresh()
              }}>Add MCP server</button>
            </div>
          </div>
          <div className="card">
            <h2>Configured servers</h2>
            {servers.map((server) => (
              <div className="toggle" key={server.id || server.name}>
                <div>
                  <strong>{server.name}</strong>
                  <div className="lede" style={{ margin: 0 }}>{server.transport} {server.command || server.url}</div>
                </div>
                <button className="btn secondary" onClick={async () => {
                  await api(`/api/mcp/${server.id}`, { method: "DELETE" })
                  refresh()
                }}>Remove</button>
              </div>
            ))}
            {!servers.length && <p className="lede">No MCP servers yet.</p>}
          </div>
        </div>
      </details>
    </div>
  )
}
