import { Link } from "react-router-dom"
import { AppearanceSettingsPane } from "../settings/AppearanceSettingsPane"
import { settingsSubmenuPath } from "../settings/settingsSubmenus"
import { VoiceHudCompact } from "../settings/VoiceHudCompact"
import type { PresentationSettings } from "./presenceTypes"

type AppearancePresenceControlsProps = {
  settings: PresentationSettings
}

export function AppearancePresenceControls({ settings }: AppearancePresenceControlsProps) {
  return (
    <div className="jarvis-presence-controls-split">
      <details className="jarvis-presence-controls">
        <summary>Voice</summary>
        <div className="jarvis-presence-controls-body">
          <VoiceHudCompact />
        </div>
      </details>

      <details className="jarvis-presence-controls">
        <summary>Appearance</summary>
        <div className="jarvis-presence-controls-body">
          <AppearanceSettingsPane settings={settings} />
          <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
            <Link to={settingsSubmenuPath("appearance")}>Open full Appearance settings</Link>
          </p>
        </div>
      </details>
    </div>
  )
}
