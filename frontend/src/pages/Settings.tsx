import { useEffect, useState } from "react"
import { api, getPrivateKey, setPrivateKey } from "../api"

export function SettingsPage() {
  const [settings, setSettings] = useState<any>(null)
  const [localKey, setLocalKey] = useState<string>(getPrivateKey())
  const [showKey, setShowKey] = useState(false)
  const [authStatus, setAuthStatus] = useState<any>(null)
  const [queueStatus, setQueueStatus] = useState<any>(null)
  const [msg, setMsg] = useState("")

  async function loadData() {
    const [s, a, q] = await Promise.all([
      api<any>("/api/settings").catch(() => null),
      api<any>("/api/auth/status").catch(() => null),
      api<any>("/api/queue").catch(() => null),
    ])
    if (s) setSettings(s)
    if (a) setAuthStatus(a)
    if (q) setQueueStatus(q)
  }

  useEffect(() => { loadData() }, [])
  if (!settings) return <div>Loading settings…</div>

  async function save(patch: any) {
    const next = await api("/api/settings", { method: "PUT", body: JSON.stringify(patch) })
    setSettings(next)
    await loadData()
  }

  async function generateKey() {
    const res = await api<any>("/api/auth/generate-key", { method: "POST" })
    if (res.private_key) {
      setLocalKey(res.private_key)
      setPrivateKey(res.private_key)
      setMsg("New private key generated and saved to server and browser.")
      await loadData()
    }
  }

  function saveLocalKeyOnly() {
    setPrivateKey(localKey)
    setMsg("Private key saved to this browser session.")
  }

  return (
    <div>
      <h1>Settings</h1>
      <p className="lede">Autonomy, remote security, timeouts, launch queue, and browser behavior.</p>
      
      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}

      <div className="card grid" style={{ maxWidth: 760 }}>
        <h2>Security & Remote Access</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Expose Jarvis remotely or over LAN with strict Private Key authentication. Every query requires <code>X-Jarvis-Key</code> or <code>Authorization: Bearer</code>.
        </p>

        <label className="row">
          <input
            type="checkbox"
            checked={settings.auth_required}
            onChange={(e) => save({ auth_required: e.target.checked })}
          />
          <strong>Require Private Key Authentication for all queries</strong>
        </label>

        <label className="row">
          <input
            type="checkbox"
            checked={settings.lan_access}
            onChange={(e) => save({ lan_access: e.target.checked })}
          />
          Allow LAN / Remote exposure (binds to <code>0.0.0.0</code>)
        </label>

        <div style={{ marginTop: 8 }}>
          <label>Private Key (Client & Server)
            <div className="row" style={{ marginTop: 6, gap: 8 }}>
              <input
                type={showKey ? "text" : "password"}
                value={localKey}
                placeholder="jarvis_pk_..."
                style={{ fontFamily: "monospace", flex: 1 }}
                onChange={(e) => setLocalKey(e.target.value)}
              />
              <button className="btn secondary" type="button" onClick={() => setShowKey(!showKey)}>
                {showKey ? "Hide" : "Show"}
              </button>
              <button className="btn secondary" type="button" onClick={saveLocalKeyOnly}>
                Save in Browser
              </button>
              <button
                className="btn secondary"
                type="button"
                onClick={() => save({ private_key: localKey }).then(() => setMsg("Private key saved to server."))}
              >
                Save to Server
              </button>
            </div>
          </label>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" type="button" onClick={generateKey}>
              Generate New Private Key
            </button>
            {authStatus?.has_key && <span className="stat" style={{ marginLeft: 12 }}>Server has active private key</span>}
          </div>
        </div>
      </div>

      <div className="card grid" style={{ maxWidth: 760, marginTop: 16 }}>
        <h2>Core Execution</h2>
        <label>Autonomy
          <select value={settings.autonomy} onChange={(e) => save({ autonomy: e.target.value })}>
            <option value="interactive">Interactive</option>
            <option value="trusted">Trusted</option>
            <option value="autonomous">Autonomous</option>
          </select>
        </label>
        <label>Execution mode
          <select value={settings.execution_mode || "balanced"} onChange={(e) => save({ execution_mode: e.target.value })}>
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="reliable">Reliable</option>
          </select>
        </label>
        <label>Default timeout (seconds)
          <input type="number" value={settings.default_timeout_seconds} onChange={(e) => save({ default_timeout_seconds: Number(e.target.value) })} />
        </label>
        <label>Retry limit
          <input type="number" value={settings.retry_limit} onChange={(e) => save({ retry_limit: Number(e.target.value) })} />
        </label>
        <label>Model profile
          <select value={settings.inference?.profile} onChange={(e) => save({ profile: e.target.value })}>
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="quality">Quality (9B thinking on)</option>
            <option value="expert">Expert (27B)</option>
          </select>
        </label>
        <label>Allowed directories (one per line)
          <textarea className="field" rows={4} defaultValue={(settings.allowed_directories || []).join("\n")}
            onBlur={(e) => save({ allowed_directories: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} />
        </label>
        <label className="row">
          <input type="checkbox" checked={!!settings.inference?.vision} onChange={(e) => save({ inference_vision: e.target.checked })} />
          Load vision projector (uses extra VRAM; leave off for text/tool work)
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.browser?.headless} onChange={(e) => save({ browser_headless: e.target.checked })} />
          Headless browser
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.backup_enabled} onChange={(e) => save({ backup_enabled: e.target.checked })} />
          Create backups before overwriting files
        </label>
      </div>

      {queueStatus && (
        <div className="card grid" style={{ maxWidth: 760, marginTop: 16 }}>
          <h2>Launch & Task Queue</h2>
          <p className="lede">
            Queue directory: <code>{queueStatus.queue_directory}</code>. Drop any <code>.json</code> or <code>.prompt</code> file to automatically run on launch or in background.
          </p>
          <div className="kv">
            <b>Pending files</b><span>{queueStatus.pending_count}</span>
            <b>Processed files</b><span>{queueStatus.processed?.length || 0}</span>
            <b>Failed files</b><span>{queueStatus.failed?.length || 0}</span>
          </div>
        </div>
      )}
    </div>
  )
}
