import { NavLink } from "react-router-dom"
import {
  SETTINGS_SUBMENUS,
  SETTINGS_SUBMENU_LABELS,
  settingsSubmenuPath,
  type SettingsSubmenu,
} from "./settingsSubmenus"

type SettingsNavProps = {
  active: SettingsSubmenu
  variant?: "portal" | "hud"
}

export function SettingsNav({ active, variant = "portal" }: SettingsNavProps) {
  return (
    <nav className={`settings-nav settings-nav-${variant}`} aria-label="Settings categories">
      <ul>
        {SETTINGS_SUBMENUS.map((id) => (
          <li key={id}>
            <NavLink
              to={settingsSubmenuPath(id)}
              className={({ isActive }) => (isActive || id === active ? "active" : "")}
              aria-current={id === active ? "page" : undefined}
            >
              {SETTINGS_SUBMENU_LABELS[id]}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
