import { useEffect, useState } from "react"
import { api } from "../api"

type Catalog = {
  tools: { name: string; description: string; enabled: boolean; risk: string }[]
  native: { id: string; name: string; available: boolean; status: string; detail: string }[]
  optional_workers: { id: string; name: string; available: boolean; status: string; detail: string }[]
  coding_workers?: { id: string; name: string; available: boolean; status: string; detail: string; tier?: number }[]
}

export function ToolsPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [coding, setCoding] = useState<CodingOverview | null>(null)
  async function refresh() {
    const [data, codingData] = await Promise.all([
      api<Catalog>("/api/tools/catalog"),
      api<CodingOverview>("/api/coding").catch(() => null),
    ])
    setCatalog(data)
    if (codingData) setCoding(codingData)
  }
  useEffect(() => { refresh() }, [])
  if (!catalog) return <div>Loading tools…</div>
  return (
    <div>
      <h1>Tools</h1>
      <p className="lede">Native tools can be enabled or disabled. The agent only receives a task-class subset plus request_capability as an escape hatch. Optional workers stay listed when they are not installed so Jarvis degrades instead of crashing.</p>
      {catalog.exposure && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Task-class exposure</h2>
          <p className="lede">Filesystem tasks do not receive Office or Docker unless requested mid-run.</p>
          {Object.entries(catalog.exposure).map(([taskClass, names]) => (
            <div className="toggle" key={taskClass}>
              <div>
                <strong>{taskClass}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>{names.join(", ")}</div>
              </div>
            </div>
          ))}
        </div>
      )}
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
      {catalog.professional_analysis && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Professional analysis</h2>
          <p className="lede" style={{ margin: "0 0 8px" }}>{catalog.professional_analysis.detail}</p>
          <div className="kv">
            <b>Analyze sensitive material</b><span>{catalog.professional_analysis.analyze_sensitive_material ? "yes" : "no"}</span>
            <b>Operational authorization separate</b><span>{catalog.professional_analysis.operational_authorization_separate ? "yes" : "no"}</span>
          </div>
        </div>
      )}
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Native backends</h2>
        {(catalog.native || []).map((item) => (
          <div className="toggle" key={item.id}>
            <div>
              <strong>{item.name}</strong>
              <div className="lede" style={{ margin: "4px 0 0" }}>{item.detail}</div>
            </div>
            <span className={`badge ${item.available ? "completed" : "queued"}`}>{item.status}</span>
          </div>
        ))}
      </div>
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
      {!!catalog.coding_workers?.length && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Software-development workers</h2>
          <p className="lede">Jarvis routes coding work to the cheapest capable worker. Paid Cursor workers stay listed when they are not configured. A worker claiming success is never completion.</p>
          {catalog.coding_workers.map((worker) => (
            <div className="toggle" key={worker.id}>
              <div>
                <strong>{worker.name}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>{worker.detail}</div>
              </div>
              <span className={`badge ${worker.available ? "completed" : "queued"}`}>{worker.status}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
