import { useEffect, useState } from "react"
import { api, getAuthToken, setAuthToken } from "../api"

type AutonomyMode = {
  name: string
  label: string
  description: string
  confirms: string
  pause_even_when_autonomous?: string[]
}

export function SettingsPage() {
  const [settings, setSettings] = useState<any>(null)
  const [lanError, setLanError] = useState("")
  const [sessionToken, setSessionToken] = useState(getAuthToken)
  useEffect(() => { api("/api/settings").then(setSettings) }, [])
  if (!settings) return <div>Loading settings…</div>
  async function save(patch: any) {
    try {
      const next = await api("/api/settings", { method: "PUT", body: JSON.stringify(patch) })
      setSettings(next)
      setLanError("")
    } catch (err) {
      setLanError(err instanceof Error ? err.message : "Save failed")
    }
  }
  const tokenSet = Boolean(settings.auth_token_configured)
  const modes: AutonomyMode[] = settings.autonomy_modes || []
  const stopList = modes[0]?.pause_even_when_autonomous || [
    "disk formatting",
    "deleting partitions",
    "destroying backups",
    "mass deletion outside the task scope",
    "credential changes",
    "financial transactions",
    "purchases",
    "disabling important system security controls",
    "publishing or sending something externally when the original task does not clearly authorize it",
  ]
  return (
    <div>
      <h1>Settings</h1>
      <p className="lede">Autonomy, execution mode, workspace, timeouts, and browser behaviour. The portal binds to 127.0.0.1 unless LAN access is on and JARVIS_AUTH_TOKEN is set.</p>
      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Autonomy</h2>
        <p className="lede">How much Jarvis may do without asking. This is not execution mode and not the model profile.</p>
        <div className="grid cards">
          {modes.map((mode) => (
            <button
              key={mode.name}
              className={`mode-card ${settings.autonomy === mode.name ? "active" : ""}`}
              onClick={() => save({ autonomy: mode.name })}
              type="button"
            >
              <strong>{mode.label}</strong>
              <span className="lede" style={{ margin: "8px 0 0", display: "block" }}>{mode.description}</span>
              <span className="lede" style={{ margin: "8px 0 0", display: "block" }}>Confirms {mode.confirms}.</span>
            </button>
          ))}
        </div>
        <p className="lede" style={{ marginTop: 16, marginBottom: 8 }}>Even Autonomous mode pauses before:</p>
        <ul className="lede" style={{ marginTop: 0 }}>
          {stopList.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
      <div className="card grid" style={{ maxWidth: 720 }}>
        <label>Execution mode
          <select value={settings.execution_mode || "balanced"} onChange={(e) => save({ execution_mode: e.target.value })}>
            <option value="fast">Fast — fewer model calls, basic verify</option>
            <option value="balanced">Balanced — plan, execute, verify</option>
            <option value="reliable">Reliable — critic, stronger verify, longer recovery</option>
          </select>
        </label>
        <p className="lede" style={{ margin: 0 }}>Execution mode is the agent loop. Model profile below is quantization and thinking, not the same thing.</p>
        <label>Default timeout (seconds)
          <input type="number" value={settings.default_timeout_seconds} onChange={(e) => save({ default_timeout_seconds: Number(e.target.value) })} />
        </label>
        <label>Retry limit
          <input type="number" value={settings.retry_limit} onChange={(e) => save({ retry_limit: Number(e.target.value) })} />
        </label>
        <label>Logging level
          <select value={settings.logging_level || "INFO"} onChange={(e) => save({ logging_level: e.target.value })}>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </label>
        <p className="lede" style={{ margin: 0 }}>Writes to {settings.log_file || "logs/jarvis.log"}. Applied immediately; default is INFO.</p>
        <label>Model profile (quant / thinking)
          <select value={settings.inference?.profile} onChange={(e) => save({ profile: e.target.value })}>
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="quality">Quality</option>
          </select>
        </label>
        <p className="lede" style={{ margin: 0 }}>Reasoning/thinking follows the model profile. Fast starts llama-server with thinking off. Balanced and Quality keep thinking on. Reload the model after changing profile.</p>
        <label>Allowed directories (one per line)
          <textarea className="field" rows={6} defaultValue={(settings.allowed_directories || []).join("\n")}
            onBlur={(e) => save({ allowed_directories: e.target.value.split("\n").map((s: string) => s.trim()).filter(Boolean) })} />
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.browser?.headless} onChange={(e) => save({ browser_headless: e.target.checked })} />
          Headless browser
        </label>
        <label>Browser timeout (milliseconds)
          <input type="number" value={settings.browser?.timeout_ms ?? 30000} onChange={(e) => save({ browser_timeout_ms: Number(e.target.value) })} />
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.backup_enabled} onChange={(e) => save({ backup_enabled: e.target.checked })} />
          Create backups before overwriting files
        </label>
        <label className="row">
          <input type="checkbox" checked={Boolean(settings.voice?.speak_results)} onChange={(e) => save({ voice_speak_results: e.target.checked })} />
          Speak completed task results with local TTS
        </label>
        <label>Whisper model (CPU)
          <select value={settings.voice?.stt_model || "tiny.en"} onChange={(e) => save({ voice_stt_model: e.target.value })}>
            <option value="tiny.en">tiny.en (fast)</option>
            <option value="tiny">tiny</option>
            <option value="base.en">base.en</option>
            <option value="base">base</option>
          </select>
        </label>
      </div>
      <div className="card" style={{ marginTop: 16, maxWidth: 720 }}>
        <h2>LAN access</h2>
        <p className="lede">Default bind is 127.0.0.1:4780. LAN bind (0.0.0.0) is only used when this is on and JARVIS_AUTH_TOKEN is in the user environment. A local llama-server process still binds 127.0.0.1:8088; pointing inference at another host is a Model page setting. Restart Jarvis after changing this. Allow Private network if Windows Firewall prompts. Phone: open <a href="/phone">/phone</a> on the same Wi-Fi and paste the token.</p>
        <div className="kv" style={{ marginBottom: 12 }}>
          <b>Auth token</b><span>{tokenSet ? "set in environment" : settings.auth_token_too_short ? "too short (need 16+ characters)" : "missing — LAN stays off"}</span>
          <b>API bind</b><span>{settings.bind_host || "127.0.0.1"}:{settings.bind_port || 4780}</span>
        </div>
        <label className="row">
          <input
            type="checkbox"
            checked={Boolean(settings.lan_access)}
            disabled={!tokenSet && !settings.lan_access}
            onChange={(e) => save({ lan_access: e.target.checked })}
          />
          Allow LAN access (requires JARVIS_AUTH_TOKEN)
        </label>
        {lanError ? <p className="lede" style={{ color: "var(--bad)" }}>{lanError}</p> : null}
        {settings.lan_access && !tokenSet ? (
          <p className="lede" style={{ color: "var(--bad)" }}>
            {settings.auth_token_too_short
              ? "JARVIS_AUTH_TOKEN is set but shorter than 16 characters, so Jarvis still binds localhost."
              : "LAN is requested in settings but the token is empty, so Jarvis still binds localhost. Set JARVIS_AUTH_TOKEN and restart."}
          </p>
        ) : null}
        <label>Auth token for this browser (LAN / phone; stored in this browser only, not settings.json)
          <input
            type="password"
            autoComplete="off"
            value={sessionToken}
            placeholder={tokenSet ? "Paste the same token on another machine" : "Set JARVIS_AUTH_TOKEN first"}
            onChange={(e) => setSessionToken(e.target.value)}
            onBlur={() => setAuthToken(sessionToken)}
          />
        </label>
        <p className="lede">{settings.listen_note}</p>
      </div>
      <InferenceServer settings={settings} save={save} />
      <PhoneUrls />
      <BackupPanel />
    </div>
  )
}

function InferenceServer({ settings, save }: { settings: any; save: (patch: any) => Promise<void> }) {
  const inf = settings.inference || {}
  const backend = inf.backend === "llama.cpp" || !inf.backend ? "llama.cpp" : "openai-compat"
  return (
    <div className="card" style={{ marginTop: 16, maxWidth: 720 }}>
      <h2>Inference server</h2>
      <p className="lede">{settings.inference_note}</p>
      <div className="kv" style={{ marginBottom: 12 }}>
        <b>Effective URL</b><span>{settings.inference_effective_url || `http://${inf.host || "127.0.0.1"}:${inf.port || 8088}/v1`}</span>
        <b>API key</b><span>{settings.inference_api_key_configured ? "set in environment" : "not set (local default)"}</span>
      </div>
      <label>Backend
        <select value={backend} onChange={(e) => save({ inference_backend: e.target.value })}>
          <option value="llama.cpp">llama.cpp on this PC</option>
          <option value="openai-compat">OpenAI-compatible (LAN / dedicated GPU)</option>
        </select>
      </label>
      {backend !== "llama.cpp" ? (
        <>
          <label>Base URL
            <input
              defaultValue={inf.base_url || ""}
              placeholder="http://192.168.1.50:8088/v1"
              onBlur={(e) => save({ inference_base_url: e.target.value })}
            />
          </label>
          <label>Host
            <input defaultValue={inf.host || ""} onBlur={(e) => save({ inference_host: e.target.value })} />
          </label>
          <label>Port
            <input
              type="number"
              defaultValue={inf.port || 8088}
              onBlur={(e) => save({ inference_port: Number(e.target.value) })}
            />
          </label>
          <label>Model id
            <input defaultValue={inf.model || "Qwen3.5-27B"} onBlur={(e) => save({ inference_model: e.target.value })} />
          </label>
        </>
      ) : null}
    </div>
  )
}

function PhoneUrls() {
  const [info, setInfo] = useState<{ urls?: string[]; note?: string; reachable_from_lan?: boolean } | null>(null)
  useEffect(() => { api<typeof info>("/api/phone").then(setInfo).catch(() => undefined) }, [])
  const urls = info?.urls || []
  return (
    <div className="card" style={{ marginTop: 16, maxWidth: 720 }}>
      <h2>Phone / Android</h2>
      <p className="lede">The phone client at `/phone` uses the same `POST /api/tasks` API as this portal. On Android Chrome: open a URL below, then Add to Home screen. Paste JARVIS_AUTH_TOKEN on the phone. Optional native WebView: `clients/android`.</p>
      {urls.map((url) => (
        <p key={url} style={{ margin: "6px 0" }}><a href={url}>{url}</a></p>
      ))}
      <p className="lede">{info?.note}</p>
    </div>
  )
}

type BackupRow = {
  id: string
  created_at?: string
  reason?: string
  files?: string[]
}

function BackupPanel() {
  const [rows, setRows] = useState<BackupRow[]>([])
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")

  async function refresh() {
    const payload = await api<{ backups: BackupRow[] }>("/api/backups")
    setRows(payload.backups || [])
  }
  useEffect(() => { refresh().catch(() => undefined) }, [])

  async function create() {
    setBusy("create")
    setError("")
    try {
      await api("/api/backups", { method: "POST" })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backup failed")
    } finally {
      setBusy("")
    }
  }

  async function restore(id: string, target: string) {
    setBusy(`${id}-${target}`)
    setError("")
    try {
      await api(`/api/backups/${id}/restore`, { method: "POST", body: JSON.stringify({ target }) })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Restore failed")
    } finally {
      setBusy("")
    }
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Settings and database backups</h2>
      <p className="lede">Copies of `settings.json` and `jarvis.db` live in `data/backups`. Startup and settings saves keep a snapshot. Restore puts that copy back; database restore needs a moment while the API reopens SQLite.</p>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="btn" disabled={!!busy} onClick={create}>{busy === "create" ? "Saving…" : "Backup now"}</button>
      </div>
      {error ? <p className="lede" style={{ color: "var(--bad)" }}>{error}</p> : null}
      {rows.length ? (
        <table>
          <thead>
            <tr>
              <th>Snapshot</th>
              <th>Contains</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  {row.id}
                  <span className="lede" style={{ display: "block", margin: 0 }}>{row.reason || ""} {row.created_at ? row.created_at.replace("T", " ").slice(0, 19) : ""}</span>
                </td>
                <td>{(row.files || []).join(", ") || "—"}</td>
                <td>
                  <div className="row">
                    <button className="btn secondary" disabled={!!busy} onClick={() => restore(row.id, "settings")}>Restore settings</button>
                    <button className="btn secondary" disabled={!!busy} onClick={() => restore(row.id, "database")}>Restore database</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="lede">No snapshots yet. Click Backup now or restart Jarvis.</p>
      )}
    </div>
  )
}
