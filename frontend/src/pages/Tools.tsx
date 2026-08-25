import { useEffect, useState } from "react"
import { api } from "../api"

type Catalog = {
  tools: { name: string; description: string; enabled: boolean; risk: string }[]
  native: { id: string; name: string; available: boolean; status: string; detail: string }[]
  optional_workers: { id: string; name: string; available: boolean; status: string; detail: string }[]
  professional_analysis?: { analyze_sensitive_material: boolean; operational_authorization_separate: boolean; detail: string }
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
      {coding && (
        <>
          <div className="card" style={{ marginTop: 16 }}>
            <h2>Software-development workers</h2>
            <p className="lede">{coding.usage.note}</p>
            {coding.workers.map((worker) => (
              <div className="toggle" key={worker.id}>
                <div>
                  <strong>{worker.name}</strong>
                  <div className="lede" style={{ margin: "4px 0 0" }}>{worker.detail}</div>
                </div>
                <span className={`badge ${worker.status === "ready" ? "completed" : "queued"}`}>{worker.status}</span>
              </div>
            ))}
          </div>
          <div className="card" style={{ marginTop: 16 }}>
            <h2>Cursor model catalog</h2>
            <p className="lede">{coding.models.note} Fast variants are {coding.models.allow_fast_variants ? "allowed" : "blocked"}.</p>
            <div className="kv" style={{ marginBottom: 12 }}>
              <b>ACP</b><span>{coding.models.status}</span>
              <b>Composer</b><span>{coding.models.composer_model}</span>
              <b>Grok</b><span>{coding.models.grok_model}</span>
            </div>
            {coding.models.models.map((model) => (
              <div className="toggle" key={model.id}>
                <div>
                  <strong>{model.label}</strong>
                  <div className="lede" style={{ margin: "4px 0 0" }}>
                    {model.detail} {model.role ? `· assigned as ${model.role}` : ""}
                  </div>
                </div>
                <span className={`badge ${model.selectable ? "completed" : "queued"}`}>
                  {model.selectable ? (model.variant === "fast" ? "fast" : "standard") : "blocked"}
                </span>
              </div>
            ))}
          </div>
          <div className="card" style={{ marginTop: 16 }}>
            <h2>Coding cost telemetry</h2>
            <div className="kv">
              <b>Cost / verified success</b><span>{money(coding.usage.cost_per_verified_success_usd)}</span>
              <b>Verified successes</b><span>{coding.usage.verified_successes}</span>
              <b>Samples</b><span>{coding.usage.samples}</span>
              <b>Total cost</b><span>{money(coding.usage.total_cost_usd)}</span>
              <b>This month</b><span>{money(coding.usage.month_cost_usd)}</span>
            </div>
            {coding.usage.by_worker.length > 0 && (
              <table style={{ marginTop: 12 }}>
                <thead>
                  <tr>
                    <th>Worker</th>
                    <th>Samples</th>
                    <th>Success</th>
                    <th>Cost / success</th>
                  </tr>
                </thead>
                <tbody>
                  {coding.usage.by_worker.map((row) => (
                    <tr key={row.worker}>
                      <td>{row.worker}</td>
                      <td>{row.samples}</td>
                      <td>{pct(row.success_rate)}</td>
                      <td>{money(row.cost_per_verified_success)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {coding.usage.by_task_class.length > 0 && (
              <p className="lede" style={{ marginTop: 12 }}>
                Local success by class:{" "}
                {coding.usage.by_task_class.map((row) => `${row.task_class} ${pct(row.local_success_rate)}`).join(" · ") || "none yet"}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
