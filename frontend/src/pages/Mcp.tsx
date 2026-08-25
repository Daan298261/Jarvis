import { useEffect, useState } from "react"
import { api } from "../api"

type McpServer = {
  id?: string
  name: string
  transport: string
  command?: string
  args?: string[]
  url?: string
  enabled?: boolean
  env_from?: string[]
  status?: string
  preset?: string
}

type McpPreset = {
  id: string
  name: string
  label: string
  description: string
  command: string
  args: string[]
  env_from: string[]
  requires: string
  docs: string
  secret_note?: string
}

export function McpPage() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [presets, setPresets] = useState<McpPreset[]>([])
  const [name, setName] = useState("custom")
  const [transport, setTransport] = useState("stdio")
  const [command, setCommand] = useState("npx")
  const [args, setArgs] = useState("-y @modelcontextprotocol/server-filesystem {desktop}")
  const [url, setUrl] = useState("")
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")

  async function refresh() {
    const [configured, catalog] = await Promise.all([
      api<McpServer[]>("/api/mcp"),
      api<McpPreset[]>("/api/mcp/presets"),
    ])
    setServers(configured)
    setPresets(catalog)
  }
  useEffect(() => { refresh() }, [])

  async function addCustom() {
    setError("")
    try {
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
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function addPreset(id: string) {
    setBusy(id)
    setError("")
    try {
      await api(`/api/mcp/presets/${id}`, { method: "POST" })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy("")
    }
  }

  const configured = new Set(servers.map((server) => server.preset || server.name))

  return (
    <div>
      <h1>MCP</h1>
      <p className="lede">Optional Model Context Protocol servers. Credentials and paired sessions stay in user-level configuration — never in git and never pasted into this form.</p>
      {error && <p className="lede" style={{ color: "var(--bad)" }}>{error}</p>}
      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Documented presets</h2>
        <p className="lede">Add a reference server. Jarvis expands {"{desktop}"} / {"{documents}"} / {"{repo}"} at runtime. WhatsApp and email require one-time account setup outside Jarvis.</p>
        {presets.map((preset) => (
          <div className="toggle" key={preset.id}>
            <div>
              <strong>{preset.label}</strong>
              <div className="lede" style={{ margin: "4px 0 0" }}>{preset.description}</div>
              <div className="lede" style={{ margin: "4px 0 0" }}>
                {preset.command} {(preset.args || []).join(" ")} · {preset.requires}
                {preset.docs ? <> · <a href={preset.docs} target="_blank" rel="noreferrer">docs</a></> : null}
              </div>
              {!!preset.env_from?.length && (
                <div className="lede" style={{ margin: "4px 0 0" }}>Needs env: {preset.env_from.join(", ")}</div>
              )}
              {preset.secret_note && <div className="lede" style={{ margin: "4px 0 0" }}>{preset.secret_note}</div>}
            </div>
            <button
              className="btn secondary"
              disabled={busy === preset.id || configured.has(preset.id) || configured.has(preset.name)}
              onClick={() => addPreset(preset.id)}
            >
              {configured.has(preset.id) || configured.has(preset.name) ? "Added" : busy === preset.id ? "Adding…" : "Add"}
            </button>
          </div>
        ))}
      </div>
      <div className="grid two">
        <div className="card">
          <h2>Add custom server</h2>
          <div className="grid" style={{ gap: 10 }}>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="name" />
            <select value={transport} onChange={(e) => setTransport(e.target.value)}>
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
            {transport === "stdio" ? (
              <>
                <input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="command" />
                <input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="args (use {desktop} not a token)" />
              </>
            ) : (
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:3000" />
            )}
            <button className="btn" onClick={addCustom}>Add MCP server</button>
          </div>
        </div>
        <div className="card">
          <h2>Configured servers</h2>
          {servers.map((server) => (
            <div className="toggle" key={server.id || server.name}>
              <div>
                <strong>{server.name}</strong>
                <div className="lede" style={{ margin: 0 }}>
                  {server.transport} {server.command || server.url} {(server.args || []).join(" ")}
                </div>
                {!!server.env_from?.length && (
                  <div className="lede" style={{ margin: "4px 0 0" }}>env from {server.env_from.join(", ")}</div>
                )}
                {server.status && <div className="lede" style={{ margin: "4px 0 0" }}>{server.status}</div>}
              </div>
              <button className="btn secondary" onClick={async () => {
                await api(`/api/mcp/${server.id}`, { method: "DELETE" })
                refresh()
              }}>Remove</button>
            </div>
          ))}
          {!servers.length && <p className="lede">No MCP servers enabled. Add a preset or a custom stdio/HTTP server.</p>}
        </div>
      </div>
    </div>
  )
}
