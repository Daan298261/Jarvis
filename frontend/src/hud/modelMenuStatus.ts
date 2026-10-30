import type { LmStudioCatalogResponse } from "../api"

/** Status wording for the HUD model menu (restored from the pre-RFC-0244 selector). */

/** Menu line shown while a model is loading, with the elapsed seconds once the first one passes. */
export function loadStatusLine(elapsedSeconds: number): string {
  return `Loading model${elapsedSeconds > 0 ? ` (${elapsedSeconds}s)` : ""}… You can close this menu.`
}

/** Second line of the trigger button. */
export function triggerMeta(input: { transferring: boolean; suiteActive: boolean; runtimesFailed: boolean }): string {
  if (input.transferring) return "Loading model"
  if (input.suiteActive) return "Cybersecurity suite · Models ▾"
  if (input.runtimesFailed) return "Offline · Models ▾"
  return "Current node · Models ▾"
}

/** Hint under the dropdown about the LM Studio catalog, or "" when the catalog is listed normally. */
export function localCatalogHint(catalog: LmStudioCatalogResponse | null, failed: boolean): string {
  if (failed) return "Local catalog unavailable."
  if (!catalog) return "Loading local models…"
  if (!catalog.profiles.length && !catalog.ungraded.length) return "No local GGUFs found under LM Studio models."
  return ""
}

export function vramHint(catalog: LmStudioCatalogResponse | null): string {
  return catalog?.vram_gb != null ? `~${catalog.vram_gb} GB VRAM` : ""
}

/** The backend's own last model error, unless the menu already shows the same text or is mid-load. */
export function backendModelError(lastError: string | undefined, shown: string[], transferring: boolean): string {
  const text = (lastError || "").trim()
  return !text || transferring || shown.includes(text) ? "" : text
}
