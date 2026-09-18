import { Link } from "react-router-dom"
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
  return (
    <>
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
