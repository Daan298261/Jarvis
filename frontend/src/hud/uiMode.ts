export type UiMode = "classic" | "hud"

// Version the preference when the primary HUD changes materially so an old
// fallback choice does not hide the new experience after upgrade. Users can
// still switch to Legacy UI and that choice persists from this version onward.
const STORAGE_KEY = "jarvis.uiMode.v2"
export const LEGACY_UI_MODE_CHANGED_EVENT = "jarvis:legacy-ui-mode-changed"

export function getUiMode(): UiMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === "classic" || raw === "hud") return raw
  } catch {
    /* ignore */
  }
  return "hud"
}

export function setUiMode(mode: UiMode, notify = true): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    /* ignore */
  }
  if (notify) {
    window.dispatchEvent(new CustomEvent<UiMode>(LEGACY_UI_MODE_CHANGED_EVENT, { detail: mode }))
  }
}
