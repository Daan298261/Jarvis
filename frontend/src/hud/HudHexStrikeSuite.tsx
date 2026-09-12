import { useCallback, useEffect, useMemo, useState } from "react"
import {
  configureHexStrike,
  getHexStrikeStatus,
  startHexStrike,
  type HexStrikeStatus,
} from "../api"
import "./hexstrike.css"

function toolEntries(tools: Record<string, unknown>): { name: string; ok: boolean }[] {
  const available = tools.available
  if (Array.isArray(available)) {
    return available.slice(0, 48).map((item) => ({
      name: String(item),
      ok: true,
    }))
  }
  return Object.entries(tools)
    .slice(0, 48)
    .map(([name, value]) => ({
      name,
      ok: value === true || value === "ok" || value === "available" || (typeof value === "object" && value !== null),
    }))
}

function processItems(processes: Record<string, unknown>): { id: string; label: string }[] {
  const items = processes.items
  if (Array.isArray(items)) {
    return items.slice(0, 12).map((item, index) => {
      if (item && typeof item === "object") {
        const row = item as Record<string, unknown>
        const id = String(row.id ?? row.pid ?? index)
        const label = String(row.name ?? row.command ?? row.tool ?? id)
        return { id, label }
      }
      return { id: String(index), label: String(item) }
    })
  }
  return Object.keys(processes)
    .slice(0, 12)
    .map((key) => ({ id: key, label: key }))
}

export function HudHexStrikeSuite() {
  const [status, setStatus] = useState<HexStrikeStatus | null>(null)
  const [pathDraft, setPathDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")

  const refresh = useCallback(async () => {
    try {
      const next = await getHexStrikeStatus()
      setStatus(next)
      setPathDraft((prev) => prev || next.install_path || "")
    } catch {
      setStatus(null)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 2500)
    return () => window.clearInterval(timer)
  }, [refresh])

  async function onSavePath() {
    setBusy(true)
    setMsg("")
    try {
      const next = await configureHexStrike({ install_path: pathDraft })
      setStatus(next)
      setMsg("Install path saved.")
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not save path.")
    } finally {
      setBusy(false)
    }
  }

  async function onStart() {
    setBusy(true)
    setMsg("")
    try {
      const next = await startHexStrike()
      setStatus(next)
      setMsg(next.running ? "HexStrike is live on loopback." : next.last_error || "HexStrike did not start.")
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not start HexStrike.")
    } finally {
      setBusy(false)
    }
  }

  const tools = useMemo(() => toolEntries(status?.tools || {}), [status?.tools])
  const processes = useMemo(() => processItems(status?.processes || {}), [status?.processes])
  const live = !!status?.running
  const stateLabel = status?.starting ? "Igniting" : live ? "Aegis live" : status?.installed ? "Standby" : "Not installed"

  return (
    <div className="hex-suite" aria-label="HexStrike AI cybersecurity suite">
      <div className="hex-suite-frame" aria-hidden />
      <header className="hex-suite-head">
        <div className="hex-suite-mark" aria-hidden>
          ⬡
        </div>
        <div className="hex-suite-titles">
          <strong>HexStrike AI</strong>
          <span>Cybersecurity suite · Jarvis gateway</span>
        </div>
        <span className={`hex-suite-pill${live ? " live" : ""}`}>{stateLabel}</span>
      </header>

      <div className="hex-suite-grid">
        <section className="hex-panel">
          <h2>Core</h2>
          <dl>
            <div>
              <dt>Bind</dt>
              <dd>
                {status?.host || "127.0.0.1"}:{status?.port || 8888}
              </dd>
            </div>
            <div>
              <dt>PID</dt>
              <dd>{status?.pid ?? "—"}</dd>
            </div>
            <div>
              <dt>Health</dt>
              <dd>{live ? "loopback /health" : "offline"}</dd>
            </div>
          </dl>
          {status?.last_error && <p className="hex-suite-error">{status.last_error}</p>}
          <button type="button" className="hex-suite-btn" disabled={busy || live} onClick={() => void onStart()}>
            {live ? "Running" : "Start HexStrike"}
          </button>
        </section>

        <section className="hex-panel">
          <h2>Telemetry</h2>
          <pre className="hex-suite-json">
            {status?.telemetry && Object.keys(status.telemetry).length
              ? JSON.stringify(status.telemetry, null, 2).slice(0, 900)
              : live
                ? "Awaiting telemetry…"
                : "Start HexStrike to stream telemetry into this console."}
          </pre>
        </section>

        <section className="hex-panel hex-panel-wide">
          <h2>Tools</h2>
          {tools.length ? (
            <ul className="hex-tool-list">
              {tools.map((tool) => (
                <li key={tool.name} className={tool.ok ? "ok" : ""}>
                  {tool.name}
                </li>
              ))}
            </ul>
          ) : (
            <p className="hex-suite-hint">
              Tool availability appears here from HexStrike <code>/health</code> once the background application is live.
            </p>
          )}
        </section>

        <section className="hex-panel">
          <h2>Processes</h2>
          {processes.length ? (
            <ul className="hex-proc-list">
              {processes.map((item) => (
                <li key={item.id}>{item.label}</li>
              ))}
            </ul>
          ) : (
            <p className="hex-suite-hint">No HexStrike jobs yet. The process dashboard is read-only through the Jarvis gateway.</p>
          )}
        </section>
      </div>

      <footer className="hex-suite-foot">
        <label>
          Install path
          <input
            value={pathDraft}
            onChange={(event) => setPathDraft(event.target.value)}
            placeholder="runtime/hexstrike-ai or full path to the clone"
            spellCheck={false}
          />
        </label>
        <button type="button" className="hex-suite-btn ghost" disabled={busy} onClick={() => void onSavePath()}>
          Save path
        </button>
        {msg && <span className="hex-suite-msg">{msg}</span>}
      </footer>
    </div>
  )
}
