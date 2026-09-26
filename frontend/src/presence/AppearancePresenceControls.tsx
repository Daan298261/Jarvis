import { Fragment, useState, type ReactNode } from "react"
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

const MENUS: { id: PresenceMenu; label: string }[] = [
  { id: "persona", label: "Persona" },
  { id: "voice", label: "Voice" },
  { id: "appearance", label: "Appearance" },
  { id: "cybersecurity", label: "Cybersecurity" },
]

function panelForMenu(id: PresenceMenu, settings: PresentationSettings): ReactNode {
  if (id === "persona") {
    return (
      <div className="jarvis-presence-controls-body jarvis-presence-controls-body-persona">
        <NamedPersonaControls />
      </div>
    )
  }
  if (id === "voice") {
    return (
      <div className="jarvis-presence-controls-body jarvis-presence-controls-body-voice">
        <VoiceProfilePicker />
        <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
          <Link to={appearanceVoiceSettingsPath("voice")}>Open full Voice settings</Link>
        </p>
      </div>
    )
  }
  if (id === "appearance") {
    return (
      <div className="jarvis-presence-controls-body">
        <AppearanceSettingsPane settings={settings} />
        <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
          <Link to={appearanceVoiceSettingsPath("appearance")}>Open full Appearance settings</Link>
        </p>
      </div>
    )
  }
  return (
    <div className="jarvis-presence-controls-body jarvis-cyber-module-body">
      <HudCybersecurityModule />
    </div>
  )
}

export function AppearancePresenceControls({ settings }: AppearancePresenceControlsProps) {
  const [openMenu, setOpenMenu] = useState<PresenceMenu | null>(null)

  function toggle(menu: PresenceMenu) {
    setOpenMenu((current) => (current === menu ? null : menu))
  }

  return (
    <table className="jarvis-presence-controls-table" role="presentation" aria-label="HUD menus">
      <tbody>
        {MENUS.map((menu) => {
          const open = openMenu === menu.id
          return (
            <Fragment key={menu.id}>
              <tr className="jarvis-presence-controls-row">
                <td>
                  <button
                    type="button"
                    className="jarvis-presence-controls-toggle"
                    aria-expanded={open}
                    onClick={() => toggle(menu.id)}
                  >
                    {open ? "▾" : "▸"} {menu.label}
                  </button>
                </td>
              </tr>
              {open && (
                <tr className="jarvis-presence-controls-body-row">
                  <td>{panelForMenu(menu.id, settings)}</td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}
