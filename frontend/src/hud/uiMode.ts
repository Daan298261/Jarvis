export type UiMode = "classic" | "hud"

const STORAGE_KEY = "jarvis.uiMode"

export function getUiMode(): UiMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === "classic" || raw === "hud") return raw
  } catch {
    /* ignore */
  }
  return "hud"
}

export function setUiMode(mode: UiMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    /* ignore */
  }
}
