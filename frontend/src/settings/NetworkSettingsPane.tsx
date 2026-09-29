import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../api"
import { settingsSubmenuPath } from "./settingsSubmenus"

type NetworkSettingsPaneProps = {
  settings: Record<string, unknown>
  localKey: string
  setLocalKey: (value: string) => void
  showKey: boolean
  setShowKey: (value: boolean) => void
  authStatus: Record<string, unknown> | null
  save: (patch: Record<string, unknown>) => Promise<void>
  saveLocalKeyOnly: () => void
  generateKey: () => Promise<void>
  setMsg: (msg: string) => void
}

export function NetworkSettingsPane({
  settings,
  localKey,
  setLocalKey,
  showKey,
  setShowKey,
  authStatus,
  save,
  saveLocalKeyOnly,
  generateKey,
  setMsg,
}: NetworkSettingsPaneProps) {
  const [elevation, setElevation] = useState<{
    elevated?: boolean
    logon_task_registered?: boolean
    logon_task_hint?: string
    needs_uac?: boolean
  } | null>(null)
  const [elevationMsg, setElevationMsg] = useState("")

  async function loadElevation() {
    const snap = await api<{
      elevated?: boolean
      logon_task_registered?: boolean
      logon_task_hint?: string
      needs_uac?: boolean
    }>("/api/system/elevation").catch(() => null)
    if (snap) setElevation(snap)
  }

  useEffect(() => {
    void loadElevation()
  }, [])

  async function askWindowsForAdmin() {
    setElevationMsg("Asking Windows…")
    const result = await api<{ detail?: string; prompted?: boolean; elevated?: boolean }>(
      "/api/system/elevation/prompt",
      { method: "POST" },
    ).catch((err: Error) => {
      setElevationMsg(err.message || "Windows did not show a prompt.")
      return null
    })
    if (result) {
      setElevationMsg(result.detail || "Approve the Windows prompt if it is on screen.")
      await loadElevation()
    }
  }

  return (
    <>
      <div className="card grid settings-pane-card">
        <h2>This PC</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          {elevation?.elevated
            ? "Jarvis is running with administrator on this session."
            : "Jarvis asks Windows for administrator itself. Approve the prompt — do not run a command."}
        </p>
        {elevation?.logon_task_hint ? <p className="lede">{elevation.logon_task_hint}</p> : null}
        {!elevation?.elevated ? (
          <div className="row">
            <button className="btn" type="button" onClick={() => void askWindowsForAdmin()}>
              Allow full PC control
            </button>
          </div>
        ) : null}
        {elevationMsg ? <p className="lede">{elevationMsg}</p> : null}
      </div>

      <div className="card grid settings-pane-card">
        <h2>Security &amp; remote access</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Expose Jarvis remotely or over LAN with strict Private Key authentication. Every query requires{" "}
          <code>X-Jarvis-Key</code> or <code>Authorization: Bearer</code>.
        </p>

        <label className="row">
          <input
            type="checkbox"
            checked={Boolean(settings.auth_required)}
            onChange={(e) => save({ auth_required: e.target.checked })}
          />
          <strong>Require Private Key Authentication for all queries</strong>
        </label>

        <label className="row">
          <input
            type="checkbox"
            checked={Boolean(settings.lan_access)}
            onChange={(e) => save({ lan_access: e.target.checked })}
          />
          Allow LAN / Remote exposure (binds to <code>0.0.0.0</code>)
        </label>

        <div style={{ marginTop: 8 }}>
          <label>Private Key (Client &amp; Server)
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
            <button className="btn" type="button" onClick={() => void generateKey()}>
              Generate New Private Key
            </button>
            {authStatus && Boolean(authStatus.has_key) && (
              <span className="stat" style={{ marginLeft: 12 }}>Server has active private key</span>
            )}
          </div>
        </div>
      </div>

      <div className="card grid settings-pane-card">
        <h2>Phone pairing</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Pair the Android companion with a 6-digit code and QR. Pairing controls live under{" "}
          <Link to={settingsSubmenuPath("phone-pairing")}>Phone Pairing</Link> in Settings.{" "}
          <Link to="/phone">Android companion home</Link> covers offline generic APK pairing.
        </p>
      </div>

      <div className="card grid settings-pane-card">
        <h2>Swarm</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Manage multi-node swarm membership, heartbeats, and delegation — without leaving the admin rail.
        </p>
        <div className="row">
          <Link className="btn" to="/swarm">
            Open Swarm admin
          </Link>
        </div>
      </div>

      <div className="card grid settings-pane-card">
        <h2>Guest portals</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Issue a scoped, revocable link so a client can see one task or decision — not this PC&apos;s
          files, tools, or settings. Preview effective permissions before the token is created.
        </p>
        <div className="row">
          <Link className="btn" to="/guest-portals">
            Open guest portals
          </Link>
        </div>
      </div>
    </>
  )
}
