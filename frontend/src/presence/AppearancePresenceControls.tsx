import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { VoiceProfilePicker } from "../tts/VoiceProfilePicker"
import { HudCybersecurityModule } from "../hud/HudCybersecurityModule"
import { AppearanceSettingsPane } from "../settings/AppearanceSettingsPane"
import { NamedPersonaControls } from "../persona/NamedPersonaControls"
import { appearanceVoiceSettingsPath } from "../settings/settingsSubmenus"
import type { PresentationSettings } from "./presenceTypes"

type AppearancePresenceControlsProps = {
  settings: PresentationSettings
}

type PresenceMenu = "persona" | "voice" | "appearance" | "cybersecurity"

function Menu({
  id,
  label,
  open,
  onToggle,
  children,
}: {
  id: PresenceMenu
  label: string
  open: boolean
  onToggle: (id: PresenceMenu) => void
  children: ReactNode
}) {
  return (
    <div className={`jarvis-presence-controls${open ? " open" : ""}`}>
      <button
        type="button"
        className="jarvis-presence-controls-toggle"
        aria-expanded={open}
        onClick={() => onToggle(id)}
      >
        {label}
      </button>
      {open ? children : null}
    </div>
  )
}

export function AppearancePresenceControls({ settings }: AppearancePresenceControlsProps) {
  const [openMenu, setOpenMenu] = useState<PresenceMenu | null>(null)

  function toggle(menu: PresenceMenu) {
    setOpenMenu((current) => (current === menu ? null : menu))
  }

  return (
    <div className="jarvis-presence-controls-split" role="toolbar" aria-label="HUD menus">
      <Menu id="persona" label="Persona" open={openMenu === "persona"} onToggle={toggle}>
        <div className="jarvis-presence-controls-body jarvis-presence-controls-body-persona">
          <NamedPersonaControls />
        </div>
      </Menu>

      <Menu id="voice" label="Voice" open={openMenu === "voice"} onToggle={toggle}>
        <div className="jarvis-presence-controls-body jarvis-presence-controls-body-voice">
          <VoiceProfilePicker />
          <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
            <Link to={appearanceVoiceSettingsPath("voice")}>Open full Voice settings</Link>
          </p>
        </div>
      </Menu>

      <Menu id="appearance" label="Appearance" open={openMenu === "appearance"} onToggle={toggle}>
        <div className="jarvis-presence-controls-body">
          <AppearanceSettingsPane settings={settings} />
          <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
            <Link to={appearanceVoiceSettingsPath("appearance")}>Open full Appearance settings</Link>
          </p>
        </div>
      </Menu>

      <Menu id="cybersecurity" label="Cybersecurity" open={openMenu === "cybersecurity"} onToggle={toggle}>
        <div className="jarvis-presence-controls-body jarvis-cyber-module-body">
          <HudCybersecurityModule />
        </div>
      </Menu>
    </div>
  )
}
