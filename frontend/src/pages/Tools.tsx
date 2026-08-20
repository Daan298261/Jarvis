import { useEffect, useState } from "react"
import { api } from "../api"

export function ToolsPage() {
  const [tools, setTools] = useState<any[]>([])
  async function refresh() {
    setTools(await api("/api/tools"))
  }
  useEffect(() => { refresh() }, [])
  return (
    <div>
      <h1>Tools</h1>
      <p className="lede">Enable or disable individual tool families. MCP tools appear after servers are configured.</p>
      <div className="card">
        {tools.map((tool) => (
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
    </div>
  )
}
