import { useEffect, useState } from "react"
import { api } from "../api"

export function ToolsPage() {
  const [tools, setTools] = useState<any[]>([])
  const [workers, setWorkers] = useState<any[]>([])
  const [trajectories, setTrajectories] = useState<any[]>([])
  const [skills, setSkills] = useState<any[]>([])
  async function refresh() {
    const [toolRows, catalog] = await Promise.all([
      api<any[]>("/api/tools"),
      api<{ workers?: any[]; trajectories?: any[]; skills?: any[] }>("/api/tools/catalog").catch(() => ({ workers: [], trajectories: [], skills: [] })),
    ])
    setTools(toolRows)
    setWorkers(catalog.workers || [])
    setTrajectories(catalog.trajectories || [])
    setSkills(catalog.skills || [])
  }
  useEffect(() => { refresh() }, [])
  return (
    <div>
      <h1>Tools</h1>
      <p className="lede">Enable or disable individual tool families. MCP tools appear after servers are configured. Optional workers stay listed even when unavailable.</p>
      {!!workers.length && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Workers</h2>
          {workers.map((worker) => (
            <div className="toggle" key={worker.name}>
              <div>
                <strong>{worker.label}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>{worker.reason}</div>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <span className={`badge ${worker.available ? "completed" : "queued"}`}>
                  {worker.enabled === false ? "disabled" : worker.available ? "available" : "unavailable"}
                </span>
                {worker.can_toggle ? (
                  <button
                    className={worker.enabled === false ? "btn secondary" : "btn"}
                    onClick={async () => {
                      await api(`/api/tools/workers/${worker.name}/${worker.enabled === false ? "enable" : "disable"}`, { method: "POST" })
                      refresh()
                    }}
                  >
                    {worker.enabled === false ? "Disabled" : "Enabled"}
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
      {!!skills.length && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Skills</h2>
          <p className="lede">Stable workflows promoted to named skills. Follow the skill instead of rediscovering the steps.</p>
          {skills.slice(0, 10).map((row) => (
            <div className="toggle" key={row.name}>
              <div>
                <strong>{row.name}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>{row.description}</div>
              </div>
              <span className={`badge ${row.builtin ? "completed" : "queued"}`}>
                {row.builtin ? "builtin" : "learned"}
              </span>
            </div>
          ))}
        </div>
      )}
      {!!trajectories.length && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Trajectories</h2>
          <p className="lede">Successful tool sequences reused on similar later tasks. Contents and chain-of-thought are not stored.</p>
          {trajectories.slice(0, 8).map((row) => (
            <div className="toggle" key={row.id}>
              <div>
                <strong>{row.task_class} · {row.worker}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>{row.goal}</div>
              </div>
              <span className={`badge ${row.stable ? "completed" : "queued"}`}>
                {row.stable ? "stable" : "candidate"} ×{row.success_count}
              </span>
            </div>
          ))}
        </div>
      )}
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
