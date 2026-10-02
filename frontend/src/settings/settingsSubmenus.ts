export const SETTINGS_SUBMENUS = [
  "appearance",
  "voice",
  "phone-pairing",
  "models",
  "network",
  "integrations",
  "advanced",
] as const

export type SettingsSubmenu = (typeof SETTINGS_SUBMENUS)[number]

/** RFC-0113 composed id — redirect only, not primary nav (RFC-0094 amend). */
export const LEGACY_SETTINGS_SUBMENU_IDS = ["appearance-voice"] as const

export type LegacySettingsSubmenu = (typeof LEGACY_SETTINGS_SUBMENU_IDS)[number]

export const SETTINGS_SUBMENU_LABELS: Record<SettingsSubmenu, string> = {
  appearance: "Appearance",
  voice: "Voice",
  "phone-pairing": "Phone Pairing",
  models: "Models & Inference",
  network: "Network & Swarm",
  integrations: "Integrations",
  advanced: "Advanced",
}

export const LAST_SETTINGS_SUBMENU_KEY = "jarvis.settings.last_submenu"

/** RFC-0094: first visit with no stored submenu opens Voice. */
export const DEFAULT_SETTINGS_SUBMENU: SettingsSubmenu = "voice"

export function isSettingsSubmenu(value: string | null | undefined): value is SettingsSubmenu {
  if (!value) return false
  return (SETTINGS_SUBMENUS as readonly string[]).includes(value)
}

export function isLegacySettingsSubmenu(value: string | null | undefined): value is LegacySettingsSubmenu {
  if (!value) return false
  return (LEGACY_SETTINGS_SUBMENU_IDS as readonly string[]).includes(value)
}

/** Map stored or alias ids to a canonical submenu (RFC-0094 migration). */
export function normalizeSettingsSubmenuId(value: string | null | undefined): SettingsSubmenu | null {
  if (!value) return null
  if (value === "appearance-voice") return "appearance"
  if (isSettingsSubmenu(value)) return value
  return null
}

export function readLastSettingsSubmenu(): SettingsSubmenu {
  try {
    const stored = localStorage.getItem(LAST_SETTINGS_SUBMENU_KEY)
    if (stored === "appearance-voice") {
      persistLastSettingsSubmenu("appearance")
      return "appearance"
    }
    const normalized = normalizeSettingsSubmenuId(stored)
    if (normalized) return normalized
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

/** Redirect `/settings/appearance-voice` to canonical Appearance or Voice. */
export function resolveAppearanceVoiceSubmenuRedirect(
  param: string | undefined,
  search: string,
  hash: string,
): SettingsSubmenu | null {
  if (param !== "appearance-voice") return null
  const section = new URLSearchParams(search).get("section")
  if (section === "voice") return "voice"
  const hashId = hash.replace(/^#/, "").trim()
  if (hashId === "voice") return "voice"
  return "appearance"
}

/** Resolve submenu from route param, `?section=`, or `#hash` (aliases). */
export function resolveSettingsSubmenuFromLocation(
  param: string | undefined,
  search: string,
  hash: string,
): SettingsSubmenu | null {
  if (param) {
    const fromParam = normalizeSettingsSubmenuId(param)
    if (fromParam) return fromParam
  }
  const section = new URLSearchParams(search).get("section")
  const fromSection = normalizeSettingsSubmenuId(section)
  if (fromSection) return fromSection
  const hashId = hash.replace(/^#/, "").trim()
  const fromHash = normalizeSettingsSubmenuId(hashId)
  if (fromHash) return fromHash
  return null
}

/** Hash to append when bare `/settings` uses legacy `?section=` / `#` aliases. */
export function legacyFocusHashFromLocation(search: string, hash: string): string {
  if (hash) return hash
  const section = new URLSearchParams(search).get("section")
  if (section === "voice") return "#voice"
  if (section === "appearance") return "#appearance"
  const hashId = hash.replace(/^#/, "").trim()
  if (hashId === "voice") return "#voice"
  if (hashId === "appearance") return "#appearance"
  return ""
}

export function settingsSubmenuPath(submenu: SettingsSubmenu, hash?: string): string {
  const base = `/settings/${submenu}`
  if (!hash) return base
  return hash.startsWith("#") ? `${base}${hash}` : `${base}#${hash}`
}

export function appearanceSettingsPath(hash?: string): string {
  return settingsSubmenuPath("appearance", hash)
}

export function voiceSettingsPath(hash?: string): string {
  return settingsSubmenuPath("voice", hash)
}
