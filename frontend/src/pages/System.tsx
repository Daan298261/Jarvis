import { useEffect, useState } from "react"
import { api, getDiagnostics, getDiagnosticsText } from "../api"
import { DesktopBridge } from "../desktop/bridge"

export function SystemPage() {
  const [info, setInfo] = useState<any>(null)
  const [selfDev, setSelfDev] = useState<any>(null)
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null)
  const [msg, setMsg] = useState("")

  async function refresh() {
    const [sys, sd, d] = await Promise.all([
      api("/api/system").catch(() => null),
      api("/api/self-dev").catch(() => null),
      getDiagnostics().catch(() => null),
    ])
    if (sys) setInfo(sys)
    if (sd) setSelfDev(sd)
    if (d) setDiag(d)
  }

  useEffect(() => { refresh() }, [])
  const hw = info?.hardware || {}
  const report = selfDev?.report
  const gate = selfDev?.latest_gate
  return (
    <div>
      <h1>System</h1>
      <p className="lede">Detected hardware used to tune local inference, plus self-development isolation controls.</p>
      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}
      {diag && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Diagnostics</h2>
          <p className="lede">Application and path status. Secrets are never included.</p>
          <div className="kv">
            {[
              "application_version",
              "frontend_version",
              "backend_version",
              "backend_status",
              "backend_pid",
              "api_port",
              "inference_backend",
              "inference_status",
              "local_model",
              "node_id",
              "hostname",
              "data_directory",
              "logs_directory",
              "runtime_directory",
              "models_directory",
            ].map((key) => (
              <div key={key} style={{ display: "contents" }}>
                <b>{key.replaceAll("_", " ")}</b>
                <span className="stat">{String(diag[key] ?? "—")}</span>
              </div>
            ))}
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button
              className="btn secondary"
              type="button"
              onClick={async () => {
                const payload = await getDiagnosticsText()
                await navigator.clipboard.writeText(payload.text)
                setMsg("Diagnostics copied (redacted).")
              }}
            >
              Copy diagnostics
            </button>
            {DesktopBridge.isDesktop() && (
              <>
                <button className="btn secondary" type="button" onClick={() => DesktopBridge.openLogs()}>
                  Open logs
                </button>
                <button className="btn secondary" type="button" onClick={() => DesktopBridge.restartBackend()}>
                  Restart backend
                </button>
              </>
            )}
          </div>
        </div>
      )}
      <div className="grid cards">
        {Object.entries(hw).map(([key, value]) => (
          <div className="card" key={key}>
            <div className="lede" style={{ marginBottom: 6 }}>{key.replaceAll("_", " ")}</div>
            <strong>{Array.isArray(value) ? value.join(", ") || "—" : String(value)}</strong>
          </div>
        ))}
      </div>
      {selfDev && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Self-development</h2>
          <p className="lede">
            Experimental work uses an isolated Git worktree. The trusted checkout is never modified or auto-merged.
            Drop <code>data/STOP_JARVIS</code> or use the stop button for an emergency halt.
          </p>
          <div className="kv" style={{ marginBottom: 12 }}>
            <b>Status</b><span className={`badge ${selfDev.status || "queued"}`}>{selfDev.status || "idle"}</span>
            <b>Kill switch</b><span>{selfDev.kill_switch ? (selfDev.kill_reason || "active") : "off"}</span>
            <b>Branch</b><span>{selfDev.branch || "—"}</span>
            <b>Start commit</b><span className="stat">{selfDev.source_commit ? String(selfDev.source_commit).slice(0, 12) : "—"}</span>
            <b>Paid dispatch</b><span>{selfDev.can_dispatch_paid ? "allowed" : "blocked (local only)"}</span>
            <b>Budget stop</b><span>{selfDev.budget_stop_reason || "none"}</span>
            <b>Experimental</b><span>{selfDev.experimental_launch?.experimental || "127.0.0.1:4781"}</span>
          </div>
          <div className="row">
            <button
              className="btn"
              onClick={async () => {
                const started = await api<any>("/api/self-dev/start", { method: "POST", body: JSON.stringify({ run_baseline: false }) })
                setSelfDev(started)
                setMsg(`Isolated worktree ${started.branch} created from ${String(started.source_commit || "").slice(0, 12)}.`)
              }}
            >
              Start isolated trial
            </button>
            <button
              className="btn danger"
              onClick={async () => {
                const stopped = await api<any>("/api/self-dev/stop", { method: "POST", body: JSON.stringify({ reason: "Portal STOP AUTONOMOUS DEVELOPMENT" }) })
                setSelfDev(stopped)
                setMsg("Emergency stop is on. Files and Git state were preserved.")
              }}
            >
              STOP AUTONOMOUS DEVELOPMENT
            </button>
            <button
              className="btn secondary"
              onClick={async () => {
                const resumed = await api<any>("/api/self-dev/resume", { method: "POST" })
                setSelfDev(resumed)
                setMsg("Kill switch cleared.")
              }}
            >
              Resume
            </button>
            {selfDev.worktree_id && (
              <>
                <button
                  className="btn secondary"
                  onClick={async () => {
                    const gateResult = await api<any>(`/api/self-dev/worktrees/${selfDev.worktree_id}/verify`, { method: "POST" })
                    await refresh()
                    setMsg(gateResult.passed ? "Verification gate passed. Merge still requires a human." : `Gate failed: ${(gateResult.reasons || []).join("; ")}`)
                  }}
                >
                  Run verification gate
                </button>
                <button
                  className="btn secondary"
                  onClick={async () => {
                    const built = await api<any>("/api/self-dev/report", { method: "POST" })
                    await refresh()
                    setMsg(`End-of-run report: ${built.tasks_completed || 0} completed, ${built.tasks_failed || 0} failed.`)
                  }}
                >
                  End-of-run report
                </button>
              </>
            )}
          </div>
          {gate && (
            <div style={{ marginTop: 14 }}>
              <strong>Latest gate:</strong> {gate.passed ? "passed" : "failed"}
              <div className="lede" style={{ margin: "6px 0 0" }}>{(gate.reasons || []).join(" · ") || "No regressions. Auto-merge remains disabled."}</div>
            </div>
          )}
          {report && (
            <div className="kv" style={{ marginTop: 14 }}>
              <b>Duration</b><span>{report.duration_seconds}s</span>
              <b>Paid cost</b><span>€{report.estimated_paid_cost_eur}</span>
              <b>Tasks</b><span>{report.tasks_completed}/{report.tasks_attempted} completed</span>
              <b>Commits</b><span>{(report.commits_created || []).length}</span>
              <b>Work / hour</b><span>{report.verified_useful_work_per_hour}</span>
              <b>Merge candidates</b><span>{(report.recommended_merge_candidates || []).join(", ") || "none"}</span>
            </div>
          )}
        </div>
      )}
      {info?.capabilities && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Backends</h2>
          {(info.capabilities.all || []).map((item: any) => (
            <div className="toggle" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>{item.detail}</div>
              </div>
              <span className={`badge ${item.available ? "completed" : "queued"}`}>{item.status}</span>
            </div>
          ))}
        </div>
      )}
      {info?.swarm && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Swarm</h2>
          <p className="lede">
            This machine is a one-node swarm until more Nodes register. The Orchestrator is the control plane; the Leader is the strongest execution node. Software workers are services on this Node. The Swarm page has full policy and budget controls.
          </p>
          <div className="kv">
            <b>Mode</b><span>{info.swarm.mode || "one-node"}</span>
            <b>Node</b><span>{info.swarm.leader?.hostname || "localhost"}</span>
            <b>Class</b><span>{info.swarm.leader?.node_class || "leader"}</span>
            <b>Orchestrator</b><span>{info.swarm.orchestrator?.kind || "control_plane"}</span>
            <b>Leader</b><span>{info.swarm.leader?.role || "leader"}</span>
            <b>Workers</b><span>{(info.swarm.workers || []).length}</span>
          </div>
          {(info.swarm.workers || []).slice(0, 12).map((worker: any) => (
            <div className="toggle" key={worker.id}>
              <div>
                <strong>{worker.name}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>
                  {worker.kind} service on this node · {worker.detail}
                </div>
              </div>
              <span className={`badge ${worker.available ? "completed" : "queued"}`}>{worker.status}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
