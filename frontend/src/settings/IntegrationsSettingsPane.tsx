import { Link } from "react-router-dom"

export function IntegrationsSettingsPane() {
  return (
    <div className="card grid settings-pane-card">
      <h2>Integrations</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Connect Gmail, WhatsApp, and other MCP servers. Setup forms live on the Connections page — this pane
        only links there so heavy UI is not duplicated.
      </p>
      <div className="row">
        <Link className="btn" to="/mcp">
          Open Connections (MCP)
        </Link>
      </div>
    </div>
  )
}
