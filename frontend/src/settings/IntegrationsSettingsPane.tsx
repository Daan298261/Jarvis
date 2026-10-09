import { CollapsibleSection } from "../components/CollapsibleSection"
import { Link } from "react-router-dom"
import { KnowledgeVaultSettingsSection } from "./KnowledgeVaultSettingsSection"
import { ReverseEngineeringSettings } from "./ReverseEngineeringSettings"

export function IntegrationsSettingsPane() {
  return (
    <div className="grid settings-pane-card">
      <CollapsibleSection className="card grid" storageKey="IntegrationsSettingsPane-Integrations" title={<span>Integrations</span>}>

        <p className="lede" style={{ margin: "0 0 12px" }}>
          Connect Gmail, WhatsApp, and other MCP servers on Connections. That page now shows live
          tool lists, refresh status, Obsidian vault, Supermemory, and optional workers.
        </p>
        <div className="row">
          <Link className="btn" to="/mcp">
            Open Connections (MCP)
          </Link>
        </div>
      </CollapsibleSection>
      <KnowledgeVaultSettingsSection />
      <ReverseEngineeringSettings />
    </div>
  )
}
