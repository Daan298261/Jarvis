import { Link } from "react-router-dom"
import { VoiceProfilePicker } from "../tts/VoiceProfilePicker"
import { HudCybersecurityModule } from "../hud/HudCybersecurityModule"
import { AppearanceSettingsPane } from "../settings/AppearanceSettingsPane"
import { appearanceVoiceSettingsPath } from "../settings/settingsSubmenus"
import type { PresentationSettings } from "./presenceTypes"

type AppearancePresenceControlsProps = {
  settings: PresentationSettings
}

export function AppearancePresenceControls({ settings }: AppearancePresenceControlsProps) {
  return (
    <div className="jarvis-presence-controls-split">
      <details className="jarvis-presence-controls">
        <summary>Voice</summary>
        <div className="jarvis-presence-controls-body jarvis-presence-controls-body-voice">
          <VoiceProfilePicker />
          <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
            <Link to={appearanceVoiceSettingsPath("voice")}>Open full Voice settings</Link>
          </p>
        </div>
      </details>

      <details className="jarvis-presence-controls">
        <summary>Appearance</summary>
        <div className="jarvis-presence-controls-body">
          <AppearanceSettingsPane settings={settings} />
          <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
            <Link to={appearanceVoiceSettingsPath("appearance")}>Open full Appearance settings</Link>
          </p>
        </div>
      </details>

      <details className="jarvis-presence-controls">
        <summary>Cybersecurity</summary>
        <div className="jarvis-presence-controls-body jarvis-cyber-module-body">
          <HudCybersecurityModule />
        </div>
      </details>
    </div>
  )
}
