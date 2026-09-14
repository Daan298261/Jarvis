import { useCallback, useEffect, useMemo, useState } from "react"
import {
  configureHexStrike,
  getHexStrikeStatus,
  installHexStrike,
  listHexStrikeScopes,
  runHexStrikeAction,
  startHexStrike,
  upsertHexStrikeScope,
  type HexStrikeScope,
  type HexStrikeStatus,
} from "../api"
import "./hexstrike.css"

function toolEntries(tools: Record<string, unknown>): { name: string; ok: boolean }[] {
  const available = tools.available
  if (Array.isArray(available)) return available.slice(0, 48).map((item) => ({ name: String(item), ok: true }))
  return Object.entries(tools)
    .slice(0, 48)
    .map(([name, value]) => ({
      name,
      ok: value === true || value === "ok" || value === "available" || (typeof value === "object" && value !== null),
    }))
}

export function HudHexStrikeSuite() {
  const [status, setStatus] = useState<HexStrikeStatus | null>(null)
  const [scopes, setScopes] = useState<HexStrikeScope[]>([])
  const [pathDraft, setPathDraft] = useState("")
  const [scopeId, setScopeId] = useState("local-host")
  const [scopeKind, setScopeKind] = useState("local_infrastructure")
  const [scopeValue, setScopeValue] = useState("local")
  const [scopeLabel, setScopeLabel] = useState("This Jarvis host")
  const [attested, setAttested] = useState(false)
  const [selectedScope, setSelectedScope] = useState("")
  const [selectedAction, setSelectedAction] = useState("host_baseline")
  const [cve, setCve] = useState("")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")

  const refresh = useCallback(async () => {
    try {
      const [next, scopeResult] = await Promise.all([getHexStrikeStatus(), listHexStrikeScopes()])
      setStatus(next)
      setScopes(scopeResult.scopes)
      setPathDraft((prev) => prev || next.install_path || "")
      setSelectedScope((prev) => prev || scopeResult.scopes[0]?.id || "")
    } catch {
      setStatus(null)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 2500)
    return () => window.clearInterval(timer)
  }, [refresh])

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true)
    setMsg("")
    try {
      await action()
      setMsg(success)
      await refresh()
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "HexStrike action failed.")
    } finally {
      setBusy(false)
    }
  }

  const tools = useMemo(() => toolEntries(status?.tools || {}), [status?.tools])
  const live = !!status?.running
  const install = status?.install
  const stateLabel = status?.starting ? "Igniting" : live ? "Aegis live" : status?.installed ? "Standby" : "Not installed"

  return (
    <div className="hex-suite" aria-label="HexStrike AI defensive cybersecurity suite">
      <div className="hex-suite-frame" aria-hidden />
      <header className="hex-suite-head">
        <div className="hex-suite-mark" aria-hidden>⬡</div>
        <div className="hex-suite-titles">
          <strong>Daybreak Blue</strong>
          <span>Defensive HexStrike gateway · local and owner-attested only</span>
        </div>
        <span className={`hex-suite-pill${live ? " live" : ""}`}>{stateLabel}</span>
      </header>

      <div className="hex-suite-grid">
        <section className="hex-panel">
          <h2>Runtime</h2>
          <dl>
            <div><dt>Bind</dt><dd>{status?.host || "127.0.0.1"}:{status?.port || 8888}</dd></div>
            <div><dt>PID</dt><dd>{status?.pid ?? "—"}</dd></div>
            <div><dt>Commit</dt><dd title={install?.approved_commit}>{install?.approved_commit?.slice(0, 10) || "—"}</dd></div>
          </dl>
          {status?.last_error && <p className="hex-suite-error">{status.last_error}</p>}
          <button type="button" className="hex-suite-btn" disabled={busy || live} onClick={() => void run(startHexStrike, "HexStrike is live on loopback.")}>
            {live ? "Running" : "Start HexStrike"}
          </button>
        </section>

        <section className="hex-panel">
          <h2>Install / Repair</h2>
          <div className="hex-progress"><span style={{ width: `${install?.progress || 0}%` }} /></div>
          <p className="hex-suite-hint">{install?.stage || "idle"} · {install?.progress || 0}%</p>
          {install?.error && <p className="hex-suite-error">{install.error}</p>}
          <button type="button" className="hex-suite-btn" disabled={busy || install?.state === "running"} onClick={() => void run(() => installHexStrike(pathDraft), "Pinned defensive runtime install started.")}>
            {install?.state === "running" ? "Installing…" : status?.installed ? "Repair" : "Install"}
          </button>
        </section>

        <section className="hex-panel hex-panel-wide">
          <h2>Defensive capabilities</h2>
          <ul className="hex-tool-list">
            {(status?.capabilities || []).map((capability) => <li key={capability.id} className="ok">{capability.title}</li>)}
          </ul>
          {!!status?.missing_dependencies?.length && <p className="hex-suite-error">Missing optional tools: {status.missing_dependencies.join(", ")}. Install them separately after review.</p>}
          {!!tools.length && <p className="hex-suite-hint">Upstream health reports {tools.filter((tool) => tool.ok).length} available tools.</p>}
        </section>

        <section className="hex-panel">
          <h2>Owner-attested scope</h2>
          <div className="hex-form">
            <input aria-label="Scope ID" value={scopeId} onChange={(event) => setScopeId(event.target.value)} placeholder="scope-id" />
            <select aria-label="Scope kind" value={scopeKind} onChange={(event) => setScopeKind(event.target.value)}>
              <option value="local_infrastructure">Local infrastructure</option>
              <option value="local_path">Local evidence path</option>
              <option value="private_host">Private LAN host</option>
              <option value="private_cidr">Private LAN range</option>
              <option value="container_image">Container image</option>
            </select>
            <input aria-label="Scope value" value={scopeValue} onChange={(event) => setScopeValue(event.target.value)} placeholder="local, path, private IP, or image" />
            <input aria-label="Scope label" value={scopeLabel} onChange={(event) => setScopeLabel(event.target.value)} placeholder="Label" />
            <label className="hex-check"><input type="checkbox" checked={attested} onChange={(event) => setAttested(event.target.checked)} />I own or am authorized to assess this asset.</label>
          </div>
          <button type="button" className="hex-suite-btn" disabled={busy || !attested} onClick={() => void run(() => upsertHexStrikeScope(scopeId, { kind: scopeKind, value: scopeValue, label: scopeLabel, attested_owned: attested }), "Defensive scope saved and audited.")}>Save scope</button>
        </section>

        <section className="hex-panel">
          <h2>Run defensive action</h2>
          <div className="hex-form">
            <select aria-label="Defensive action" value={selectedAction} onChange={(event) => setSelectedAction(event.target.value)}>
              {(status?.capabilities || []).map((capability) => <option key={capability.id} value={capability.id}>{capability.title}</option>)}
            </select>
            <select aria-label="Approved scope" value={selectedScope} onChange={(event) => setSelectedScope(event.target.value)}>
              <option value="">Choose an approved scope</option>
              {scopes.map((scope) => <option key={scope.id} value={scope.id}>{scope.label || scope.id}</option>)}
            </select>
            {selectedAction === "threat_intel_lookup" && <input aria-label="CVE identifier" value={cve} onChange={(event) => setCve(event.target.value)} placeholder="CVE-2026-12345" />}
          </div>
          <button type="button" className="hex-suite-btn" disabled={busy || !selectedScope || !live} onClick={() => void run(() => runHexStrikeAction({ action: selectedAction, scope_id: selectedScope, options: cve ? { cve } : {} }), "Defensive action completed and audited.")}>Run defense</button>
          <ul className="hex-proc-list">
            {(status?.managed_jobs || []).slice(-6).map((job) => <li key={job.id}>{job.action}: {job.status}</li>)}
          </ul>
        </section>
      </div>

      <footer className="hex-suite-foot">
        <label>Install path<input value={pathDraft} onChange={(event) => setPathDraft(event.target.value)} placeholder="runtime/hexstrike-ai" spellCheck={false} /></label>
        <button type="button" className="hex-suite-btn ghost" disabled={busy} onClick={() => void run(() => configureHexStrike({ install_path: pathDraft }), "Install path saved.")}>Save path</button>
        <a className="hex-suite-help" href="/help?topic=hexstrike-blue">Defensive setup help</a>
        {msg && <span className="hex-suite-msg" role="status">{msg}</span>}
      </footer>
    </div>
  )
}
