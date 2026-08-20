import { useEffect, useState } from "react"
import { api } from "../api"

export function McpPage() {
  const [servers, setServers] = useState<any[]>([])
  const [name, setName] = useState("filesystem")
  const [transport, setTransport] = useState("stdio")
  const [command, setCommand] = useState("npx")
  const [args, setArgs] = useState("-y @modelcontextprotocol/server-filesystem C:/Users/daanv/Desktop")
  const [url, setUrl] = useState("")

  async function refresh() {
    setServers(await api("/api/mcp"))
  }
  useEffect(() => { refresh() }, [])

  return (
    <div>
      <h1>MCP</h1>
      <p className="lede">Add stdio or HTTP MCP servers without changing application code. Credentials belong in environment variables, never in source.</p>
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
                body: JSON.stringify({
                  name,
                  transport,
                  command,
                  args: args.split(" ").filter(Boolean),
                  url,
                  enabled: true,
                }),
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
    </div>
  )
}
