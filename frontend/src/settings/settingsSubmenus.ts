export const SETTINGS_SUBMENUS = [
  "voice",
  "appearance",
  "models",
  "network",
  "integrations",
  "advanced",
] as const

export type SettingsSubmenu = (typeof SETTINGS_SUBMENUS)[number]

export const SETTINGS_SUBMENU_LABELS: Record<SettingsSubmenu, string> = {
  voice: "Voice",
  appearance: "Appearance",
  models: "Models / Inference",
  network: "Network / Companion",
  integrations: "Integrations",
  advanced: "Advanced",
}

export const LAST_SETTINGS_SUBMENU_KEY = "jarvis.settings.last_submenu"

export const DEFAULT_SETTINGS_SUBMENU: SettingsSubmenu = "voice"

export function isSettingsSubmenu(value: string | null | undefined): value is SettingsSubmenu {
  if (!value) return false
  return (SETTINGS_SUBMENUS as readonly string[]).includes(value)
}

export function readLastSettingsSubmenu(): SettingsSubmenu {
  try {
    const stored = localStorage.getItem(LAST_SETTINGS_SUBMENU_KEY)
    if (isSettingsSubmenu(stored)) return stored
  } catch {
    /* ignore */
  }
  return DEFAULT_SETTINGS_SUBMENU
}

export function persistLastSettingsSubmenu(submenu: SettingsSubmenu): void {
  try {
    localStorage.setItem(LAST_SETTINGS_SUBMENU_KEY, submenu)
  } catch {
    /* ignore */
  }
}

/** Resolve submenu from route param, `?section=`, or `#hash` (aliases). */
export function resolveSettingsSubmenuFromLocation(
  param: string | undefined,
  search: string,
  hash: string,
): SettingsSubmenu | null {
  if (isSettingsSubmenu(param)) return param
  const section = new URLSearchParams(search).get("section")
  if (isSettingsSubmenu(section)) return section
  const hashId = hash.replace(/^#/, "").trim()
  if (isSettingsSubmenu(hashId)) return hashId
  return null
}

export function settingsSubmenuPath(submenu: SettingsSubmenu): string {
  return `/settings/${submenu}`
}
