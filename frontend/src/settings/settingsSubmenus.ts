export const SETTINGS_SUBMENUS = [
  "appearance-voice",
  "phone-pairing",
  "models",
  "network",
  "integrations",
  "advanced",
] as const

export type SettingsSubmenu = (typeof SETTINGS_SUBMENUS)[number]

/** RFC-0094 route ids kept as redirect aliases only (not primary nav). */
export const LEGACY_SETTINGS_SUBMENU_IDS = ["voice", "appearance"] as const

export type LegacySettingsSubmenu = (typeof LEGACY_SETTINGS_SUBMENU_IDS)[number]

export const SETTINGS_SUBMENU_LABELS: Record<SettingsSubmenu, string> = {
  "appearance-voice": "Appearance & Voice",
  "phone-pairing": "Phone Pairing",
  models: "Models & Inference",
  network: "Network & Swarm",
  integrations: "Integrations",
  advanced: "Advanced",
}

export const LAST_SETTINGS_SUBMENU_KEY = "jarvis.settings.last_submenu"

export const DEFAULT_SETTINGS_SUBMENU: SettingsSubmenu = "appearance-voice"

export function isSettingsSubmenu(value: string | null | undefined): value is SettingsSubmenu {
  if (!value) return false
  return (SETTINGS_SUBMENUS as readonly string[]).includes(value)
}

export function isLegacySettingsSubmenu(value: string | null | undefined): value is LegacySettingsSubmenu {
  if (!value) return false
  return (LEGACY_SETTINGS_SUBMENU_IDS as readonly string[]).includes(value)
}

/** Map stored or alias ids to a canonical submenu (RFC-0113 migration). */
export function normalizeSettingsSubmenuId(value: string | null | undefined): SettingsSubmenu | null {
  if (!value) return null
  if (value === "voice" || value === "appearance") return "appearance-voice"
  if (isSettingsSubmenu(value)) return value
  return null
}

export function readLastSettingsSubmenu(): SettingsSubmenu {
  try {
    const stored = localStorage.getItem(LAST_SETTINGS_SUBMENU_KEY)
    const normalized = normalizeSettingsSubmenuId(stored)
    if (normalized) {
      if (stored === "voice" || stored === "appearance") {
        persistLastSettingsSubmenu(normalized)
      }
      return normalized
    }
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

/** Redirect legacy `/settings/voice` and `/settings/appearance` paths. */
export function resolveLegacySettingsSubmenuRedirect(
  param: string | undefined,
  hash: string,
): { submenu: SettingsSubmenu; hash: string } | null {
  if (param === "voice") {
    const focus = hash.replace(/^#/, "").trim()
    return { submenu: "appearance-voice", hash: focus ? hash : "#voice" }
  }
  if (param === "appearance") {
    const focus = hash.replace(/^#/, "").trim()
    return { submenu: "appearance-voice", hash: focus ? hash : "#appearance" }
  }
  return null
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

export function appearanceVoiceSettingsPath(focus?: "voice" | "appearance"): string {
  return settingsSubmenuPath("appearance-voice", focus ? `#${focus}` : undefined)
}
