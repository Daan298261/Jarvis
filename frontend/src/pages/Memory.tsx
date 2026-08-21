import { useEffect, useState } from "react"
import { api } from "../api"

type Skill = {
  id: string
  name: string
  description: string
  task_class: string
  tools: string[]
  steps: string[]
  verification: string
  origin: string
  times_used: number
  enabled: boolean
}

type Trajectory = {
  id: number
  task_class: string
  goal: string
  outcome: string
  tools: string[]
  recovery: string
  reuse_count: number
  duration_seconds: number
}

export function MemoryPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [trajectories, setTrajectories] = useState<Trajectory[]>([])
  const [busy, setBusy] = useState(false)

  async function refresh() {
    const [s, t] = await Promise.all([
      api<Skill[]>("/api/memory/skills"),
      api<Trajectory[]>("/api/memory/trajectories"),
    ])
    setSkills(s)
    setTrajectories(t)
  }
  useEffect(() => { refresh() }, [])

  async function promote() {
    setBusy(true)
    try {
      await api("/api/memory/skills/promote", { method: "POST" })
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h1>Memory</h1>
      <p className="lede">
        Skills are workflows Jarvis has repeated successfully. Trajectories record which tools worked, what failed, and how it recovered.
      </p>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Skills</h2>
          <button className="btn" disabled={busy} onClick={promote}>Promote repeated workflows</button>
        </div>
        {!skills.length && <p className="lede">No skills yet. A workflow is promoted after it succeeds several times.</p>}
        {skills.map((skill) => (
          <div className="toggle" key={skill.id}>
            <div>
              <strong>{skill.name}</strong>
              <div className="lede" style={{ margin: "4px 0 0" }}>{skill.description}</div>
              <div className="lede" style={{ margin: "4px 0 0" }}>
                {skill.tools.join(" → ") || "no tools"} · used {skill.times_used}× · {skill.origin}
              </div>
            </div>
            <button
              className={skill.enabled ? "btn" : "btn secondary"}
              onClick={async () => {
                await api(`/api/memory/skills/${skill.id}/${skill.enabled ? "disable" : "enable"}`, { method: "POST" })
                refresh()
              }}
            >
              {skill.enabled ? "Enabled" : "Disabled"}
            </button>
          </div>
        ))}
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Trajectories</h2>
        {!trajectories.length && <p className="lede">Nothing recorded yet.</p>}
        {trajectories.length > 0 && (
          <table>
            <thead>
              <tr><th>Goal</th><th>Class</th><th>Outcome</th><th>Tools</th><th>Recovery</th><th>Reused</th></tr>
            </thead>
            <tbody>
              {trajectories.map((row) => (
                <tr key={row.id}>
                  <td>{row.goal}</td>
                  <td>{row.task_class || "—"}</td>
                  <td><span className={`badge ${row.outcome}`}>{row.outcome}</span></td>
                  <td>{row.tools.join(", ") || "—"}</td>
                  <td>{row.recovery || "—"}</td>
                  <td>{row.reuse_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
