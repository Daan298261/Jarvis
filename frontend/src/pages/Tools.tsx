import { useEffect, useState } from "react"
import { api } from "../api"

type Catalog = {
  tools: { name: string; description: string; enabled: boolean; risk: string }[]
  native: { id: string; name: string; available: boolean; status: string; detail: string }[]
  optional_workers: { id: string; name: string; available: boolean; status: string; detail: string }[]
  cursor_acp?: { status?: string; detail?: string; command?: string; available?: boolean; session_id?: string }
}

export function ToolsPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  async function refresh() {
    const data = await api<Catalog>("/api/tools/catalog")
    setCatalog(data)
  }
  useEffect(() => { refresh() }, [])
  if (!catalog) return <div>Loading tools…</div>
  return (
    <div>
      <h1>Tools</h1>
      <p className="lede">Native tools can be enabled or disabled. Optional workers stay listed when they are not installed so Jarvis degrades instead of crashing.</p>
      <div className="card">
        {catalog.tools.map((tool) => (
          <div className="toggle" key={tool.name}>
            <div>
              <strong>{tool.name}</strong>
              <div className="lede" style={{ margin: "4px 0 0" }}>{tool.description}</div>
            </div>
            <button
              className={tool.enabled ? "btn" : "btn secondary"}
              onClick={async () => {
                await api(`/api/tools/${tool.name}/${tool.enabled ? "disable" : "enable"}`, { method: "POST" })
                refresh()
              }}
            >
              {tool.enabled ? "Enabled" : "Disabled"}
            </button>
          </div>
        ))}
      </div>
      {catalog.cursor_acp && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Cursor ACP</h2>
          <p className="lede">{catalog.cursor_acp.detail}</p>
          <div className="toggle">
            <div>
              <strong>{catalog.cursor_acp.command || "agent acp"}</strong>
              <div className="lede" style={{ margin: "4px 0 0" }}>
                Session IDs persist. Routine plan questions are auto-answered only for isolated work.
              </div>
            </div>
            <span className={`badge ${catalog.cursor_acp.available ? "completed" : "queued"}`}>{catalog.cursor_acp.status}</span>
          </div>
        </div>
      )}
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Optional workers</h2>
        {catalog.optional_workers.map((worker) => (
          <div className="toggle" key={worker.id}>
            <div>
              <strong>{worker.name}</strong>
              <div className="lede" style={{ margin: "4px 0 0" }}>{worker.detail}</div>
            </div>
            <span className={`badge ${worker.available ? "completed" : "queued"}`}>{worker.status}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
