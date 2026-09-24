import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../api"

type SkillParam = { name: string; kind?: string; examples?: string[] }

type Skill = {
  id: string
  name: string
  description: string
  task_class: string
  tools: string[]
  steps: Array<string | { tool?: string; arguments?: Record<string, unknown> }>
  parameters: SkillParam[]
  verification: string
  origin: string
  times_used: number
  enabled: boolean
  executable: boolean
  runnable?: boolean
  requires_secret?: boolean
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

type SupermemoryModule = {
  id: "supermemory"
  name: string
  description: string
  enabled: boolean
  auto_start: boolean
  installed: boolean
  install_status: "idle" | "installing" | "ready" | "error"
  install_detail: string
  install_error: string
  running: boolean
  managed: boolean
  starting: boolean
  healthy: boolean
  base_url: string
  console_url: string
  platform_supported: boolean
  native_fallback: boolean
  authoritative_store: string
  owner_vault: string
}

function stepLabel(step: Skill["steps"][number]) {
  if (typeof step === "string") return step
  const tool = step.tool || "tool"
  const args = step.arguments || {}
  const keys = Object.keys(args)
  return keys.length ? `${tool} (${keys.join(", ")})` : tool
}

export function MemoryPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [trajectories, setTrajectories] = useState<Trajectory[]>([])
  const [busy, setBusy] = useState(false)
  const [paramValues, setParamValues] = useState<Record<string, Record<string, string>>>({})
  const [runLog, setRunLog] = useState<Record<string, string>>({})
  const [supermemory, setSupermemory] = useState<SupermemoryModule | null>(null)
  const [moduleBusy, setModuleBusy] = useState(false)
  const [moduleMessage, setModuleMessage] = useState("")
  const [moduleError, setModuleError] = useState("")

  async function refreshSupermemory() {
    const result = await api<{ module?: SupermemoryModule } & SupermemoryModule>("/api/modules/catalog/supermemory")
    setSupermemory(result.module || result)
  }

  async function refresh() {
    const [s, t] = await Promise.all([
      api<Skill[]>("/api/memory/skills"),
      api<Trajectory[]>("/api/memory/trajectories"),
    ])
    setSkills(s)
    setTrajectories(t)
  }
  useEffect(() => {
    refresh()
    refreshSupermemory().catch((err: unknown) => setModuleError(err instanceof Error ? err.message : String(err)))
  }, [])

  useEffect(() => {
    if (supermemory?.install_status !== "installing" && !supermemory?.starting) return
    const timer = window.setInterval(() => {
      refreshSupermemory().catch(() => undefined)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [supermemory?.install_status, supermemory?.starting])

  async function moduleAction(action: "install" | "start" | "stop") {
    setModuleBusy(true)
    setModuleError("")
    setModuleMessage("")
    try {
      const result = await api<{ module?: SupermemoryModule; detail?: string } & Partial<SupermemoryModule>>(
        `/api/modules/catalog/supermemory/${action}`,
        { method: "POST" },
      )
      setSupermemory((result.module || result) as SupermemoryModule)
      setModuleMessage(result.detail || (action === "install" ? "Installation started." : `Supermemory ${action}ed.`))
    } catch (err: unknown) {
      setModuleError(err instanceof Error ? err.message : String(err))
    } finally {
      setModuleBusy(false)
    }
  }

  async function toggleSupermemory() {
    if (!supermemory) return
    setModuleBusy(true)
    setModuleError("")
    try {
      const result = await api<{ module: SupermemoryModule }>("/api/modules/catalog/supermemory/enable", {
        method: "POST",
        body: JSON.stringify({ enabled: !supermemory.enabled }),
      })
      setSupermemory(result.module)
      setModuleMessage(result.module.enabled ? "Supermemory recall enabled." : "Supermemory recall disabled; native memory remains active.")
    } catch (err: unknown) {
      setModuleError(err instanceof Error ? err.message : String(err))
    } finally {
      setModuleBusy(false)
    }
  }

  async function promote() {
    setBusy(true)
    try {
      await api("/api/memory/skills/promote", { method: "POST" })
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function runSkill(skill: Skill) {
    setBusy(true)
    try {
      const result = await api<{ ok: boolean; results: { tool: string; success: boolean; output: string; error: string }[] }>(
        `/api/memory/skills/${skill.id}/run`,
        { method: "POST", body: JSON.stringify({ parameters: paramValues[skill.id] || {} }) },
      )
      const summary = (result.results || []).map((row) => `${row.tool}: ${row.success ? "ok" : row.error || "failed"}`).join("\n")
      setRunLog((current) => ({ ...current, [skill.id]: summary || (result.ok ? "Skill ran." : "Skill failed.") }))
      await refresh()
    } catch (err: any) {
      setRunLog((current) => ({ ...current, [skill.id]: err.message || String(err) }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h1>Memory</h1>
      <p className="lede">
        Skills are workflows Jarvis has repeated successfully. When tool arguments were recorded, they become parameters and the skill can run itself instead of only guiding the model.
      </p>
      <p className="lede" style={{ marginTop: -12 }}>
        Anzu 1.0 Skill Forge (approve → activate, no auto-publish) is on{" "}
        <Link to="/skills">Modules / Skills</Link>. Identity, projects, lessons, and other saved notes live on{" "}
        <Link to="/context">Context</Link>.
      </p>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 260 }}>
            <h2 style={{ margin: 0 }}>Semantic memory module</h2>
            <p className="lede" style={{ marginBottom: 8 }}>
              Supermemory runs locally for semantic recall. ContextRepo stays authoritative and is always the fallback;
              Obsidian stays your editable knowledge vault.
            </p>
            {supermemory && (
              <div className="lede" style={{ margin: 0 }}>
                <span className={`badge ${supermemory.healthy ? "completed" : supermemory.install_status === "error" ? "failed" : "queued"}`}>
                  {supermemory.healthy ? "healthy" : supermemory.install_status === "installing" ? "installing" : supermemory.installed ? "stopped" : "not installed"}
                </span>
                {supermemory.installed ? " · installed" : ""}
                {supermemory.managed ? " · Jarvis managed" : ""}
                {supermemory.auto_start ? " · auto-start" : ""}
                {supermemory.enabled ? " · recall enabled" : " · native memory only"}
              </div>
            )}
          </div>
          <div className="row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
            {supermemory && !supermemory.installed && (
              <button className="btn" disabled={moduleBusy || supermemory.install_status === "installing" || !supermemory.platform_supported} onClick={() => moduleAction("install")}>
                {supermemory.install_status === "installing" ? "Installing…" : "Install locally"}
              </button>
            )}
            {supermemory?.installed && !supermemory.running && (
              <button className="btn" disabled={moduleBusy || supermemory.starting} onClick={() => moduleAction("start")}>
                {supermemory.starting ? "Starting…" : "Start"}
              </button>
            )}
            {supermemory?.running && supermemory.managed && (
              <button className="btn secondary" disabled={moduleBusy} onClick={() => moduleAction("stop")}>Stop</button>
            )}
            {supermemory?.installed && (
              <button className={supermemory.enabled ? "btn" : "btn secondary"} disabled={moduleBusy} onClick={toggleSupermemory}>
                {supermemory.enabled ? "Enabled" : "Disabled"}
              </button>
            )}
            {supermemory?.running && (
              <a className="btn secondary" href={supermemory.console_url} target="_blank" rel="noreferrer">Open local console</a>
            )}
          </div>
        </div>
        {supermemory?.install_detail && <p className="lede" style={{ marginBottom: 0 }}>{supermemory.install_detail}</p>}
        {(moduleError || supermemory?.install_error) && (
          <p className="lede" style={{ color: "var(--danger, #ff6b6b)", marginBottom: 0 }}>{moduleError || supermemory?.install_error}</p>
        )}
        {moduleMessage && <p className="lede" style={{ color: "var(--ok)", marginBottom: 0 }}>{moduleMessage}</p>}
      </div>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Skills</h2>
          <button className="btn" disabled={busy} onClick={promote}>Promote repeated workflows</button>
        </div>
        {!skills.length && <p className="lede">No skills yet. A workflow is promoted after it succeeds several times.</p>}
        {skills.map((skill) => (
          <div className="toggle" key={skill.id} style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 240 }}>
              <strong>{skill.name}</strong>
              <div className="lede" style={{ margin: "4px 0 0" }}>{skill.description}</div>
              <div className="lede" style={{ margin: "4px 0 0" }}>
                {skill.tools.join(" → ") || "no tools"} · used {skill.times_used}× · {skill.origin}
                {skill.origin === "browser_promoted" ? " · BrowserCode" : ""}
                {skill.requires_secret ? " · needs secrets" : ""}
                {skill.executable || skill.runnable ? " · executable" : " · guide only"}
              </div>
              <div className="lede" style={{ margin: "4px 0 0" }}>Steps: {skill.steps.map(stepLabel).join(" → ") || "—"}</div>
              {(skill.executable || skill.runnable) && (
                <div style={{ marginTop: 8 }}>
                  {skill.parameters.map((param) => (
                    <label key={param.name} className="lede" style={{ display: "block", marginBottom: 6 }}>
                      {param.name}{param.kind === "secret" ? " (not stored)" : ""}
                      <input
                        type={param.kind === "secret" ? "password" : "text"}
                        autoComplete="off"
                        value={paramValues[skill.id]?.[param.name] || ""}
                        placeholder={param.kind === "secret" ? "required · not stored" : (param.examples?.[0] || param.kind || param.name)}
                        onChange={(event) =>
                          setParamValues((current) => ({
                            ...current,
                            [skill.id]: { ...(current[skill.id] || {}), [param.name]: event.target.value },
                          }))
                        }
                      />
                    </label>
                  ))}
                  <button className="btn" disabled={busy} onClick={() => runSkill(skill)}>Run skill</button>
                  {runLog[skill.id] && <pre className="report" style={{ marginTop: 8 }}>{runLog[skill.id]}</pre>}
                </div>
              )}
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
