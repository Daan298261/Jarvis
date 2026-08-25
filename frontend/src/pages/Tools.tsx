import { useEffect, useState } from "react"
import { api } from "../api"

type Catalog = {
  tools: { name: string; description: string; enabled: boolean; risk: string }[]
  native: { id: string; name: string; available: boolean; status: string; detail: string }[]
  optional_workers: { id: string; name: string; available: boolean; status: string; detail: string }[]
}

type CodingOverview = {
  workers: { id: string; name: string; status: string; detail: string }[]
  models: {
    status: string
    command: string | null
    note: string
    allow_fast_variants: boolean
    composer_model: string
    grok_model: string
    models: { id: string; label: string; variant: string; selectable: boolean; role: string; detail: string }[]
  }
  usage: {
    cost_per_verified_success_usd: number | null
    verified_successes: number
    samples: number
    total_cost_usd: number
    month_cost_usd: number
    by_worker: { worker: string; samples: number; verified: number; cost_usd: number; success_rate: number | null; cost_per_verified_success: number | null }[]
    by_task_class: { task_class: string; samples: number; local_success_rate: number | null; cost_per_verified_success: number | null }[]
    note: string
  }
}

function money(value: number | null | undefined) {
  if (value == null) return "n/a"
  return `$${value.toFixed(4)}`
}

function pct(value: number | null | undefined) {
  if (value == null) return "n/a"
  return `${Math.round(value * 1000) / 10}%`
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
