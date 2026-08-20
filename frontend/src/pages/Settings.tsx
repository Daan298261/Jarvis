import { useEffect, useState } from "react"
import { api } from "../api"

export function SettingsPage() {
  const [settings, setSettings] = useState<any>(null)
  useEffect(() => { api("/api/settings").then(setSettings) }, [])
  if (!settings) return <div>Loading settings…</div>
  async function save(patch: any) {
    const next = await api("/api/settings", { method: "PUT", body: JSON.stringify(patch) })
    setSettings(next)
  }
  return (
    <div>
      <h1>Settings</h1>
      <p className="lede">Autonomy, workspace, timeouts, and browser behaviour. LAN access requires JARVIS_AUTH_TOKEN.</p>
      <div className="card grid" style={{ maxWidth: 720 }}>
        <label>Autonomy
          <select value={settings.autonomy} onChange={(e) => save({ autonomy: e.target.value })}>
            <option value="interactive">Interactive</option>
            <option value="trusted">Trusted</option>
            <option value="autonomous">Autonomous</option>
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
            <option value="quality">Quality</option>
          </select>
        </label>
        <label>Allowed directories (one per line)
          <textarea className="field" rows={6} defaultValue={(settings.allowed_directories || []).join("\n")}
            onBlur={(e) => save({ allowed_directories: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} />
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.browser?.headless} onChange={(e) => save({ browser_headless: e.target.checked })} />
          Headless browser
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.backup_enabled} onChange={(e) => save({ backup_enabled: e.target.checked })} />
          Create backups before overwriting files
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.lan_access} onChange={(e) => save({ lan_access: e.target.checked })} />
          Allow LAN access (requires auth token)
        </label>
      </div>
    </div>
  )
}
