import { Fragment, useEffect, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { VoiceProfilePicker } from "../tts/VoiceProfilePicker"
import { HudCybersecurityModule } from "../hud/HudCybersecurityModule"
import { AppearanceSettingsPane } from "../settings/AppearanceSettingsPane"
import { NamedPersonaControls } from "../persona/NamedPersonaControls"
import { CollapsibleSection } from "../components/CollapsibleSection"
import { appearanceSettingsPath, voiceSettingsPath } from "../settings/settingsSubmenus"
import type { PresentationSettings } from "./presenceTypes"

type AppearancePresenceControlsProps = {
  settings: PresentationSettings
  onOpenChange?: (open: boolean, menu: PresenceMenu | null) => void
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
        <CollapsibleSection title="Persona options" storageKey="hud-persona-options"><NamedPersonaControls /></CollapsibleSection>
      </div>
    )
  }
  if (id === "voice") {
    return (
      <div className="jarvis-presence-controls-body jarvis-presence-controls-body-voice">
        <CollapsibleSection title="Voice profiles" storageKey="hud-voice-profiles"><VoiceProfilePicker /></CollapsibleSection>
        <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
          <Link to={voiceSettingsPath()}>Open full Voice settings</Link>
        </p>
      </div>
    )
  }
  if (id === "appearance") {
    return (
      <div className="jarvis-presence-controls-body">
        <CollapsibleSection title="Appearance options" storageKey="hud-appearance-options"><AppearanceSettingsPane settings={settings} showPersona={false} /></CollapsibleSection>
        <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
          <Link to={appearanceSettingsPath()}>Open full Appearance settings</Link>
        </p>
      </div>
    )
  }
  return (
    <div className="jarvis-presence-controls-body jarvis-cyber-module-body">
      <CollapsibleSection title="Cybersecurity options" storageKey="hud-cybersecurity-options"><HudCybersecurityModule /></CollapsibleSection>
    </div>
  )
}

export function AppearancePresenceControls({ settings, onOpenChange }: AppearancePresenceControlsProps) {
  const [openMenu, setOpenMenu] = useState<PresenceMenu | null>(null)
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("anzu.hud.menus.collapsed") === "true" } catch { return false }
  })

  useEffect(() => {
    onOpenChange?.(openMenu !== null, openMenu)
    return () => onOpenChange?.(false, null)
  }, [onOpenChange, openMenu])

  function toggle(menu: PresenceMenu) {
    setOpenMenu((current) => (current === menu ? null : menu))
  }

  function toggleRail() {
    const next = !collapsed
    setCollapsed(next)
    if (next) setOpenMenu(null)
    try { localStorage.setItem("anzu.hud.menus.collapsed", String(next)) } catch { /* Storage is optional. */ }
  }

  return (
    <table className={`jarvis-presence-controls-table${openMenu ? " open" : ""}${collapsed ? " collapsed" : ""}`} role="presentation" aria-label="HUD menus">
      <tbody>
        <tr><td><button type="button" className="jarvis-presence-controls-toggle" aria-label={collapsed ? "Expand menus" : "Collapse menus"} aria-expanded={!collapsed} onClick={toggleRail}>{collapsed ? "☰" : "‹ Menus"}</button></td></tr>
        {!collapsed && MENUS.map((menu) => {
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
                    <span aria-hidden="true">{open ? "▾" : "▸"}</span> {menu.label}
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
