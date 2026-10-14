import { api, startHexStrike } from "../api"

/** Owner-facing toast when cyber.hexstrike is already granted and the suite starts. */
export const HEXSTRIKE_READY_MESSAGE = "HexStrike AI suite ready."

/** Owner-facing toast when start is deferred until Daybreak (ask / not granted). */
export const HEXSTRIKE_DEFER_START_MESSAGE =
  "HexStrike selected. Open Daybreak and press Start when you want the suite running."

/**
 * Real permission state comes from GET /api/permissions/cyber.hexstrike
 * (`status` is the evaluated decision: allow | ask | deny).
 * Only `allow` means the owner already granted the suite - safe to auto-start.
 */
export function hexStrikePermissionAllowsAutostart(
  status: string | null | undefined,
): boolean {
  return (status || "").trim().toLowerCase() === "allow"
}

export async function readHexStrikePermissionGranted(): Promise<boolean> {
  try {
    const permission = await api<{ status?: string }>("/api/permissions/cyber.hexstrike")
    return hexStrikePermissionAllowsAutostart(permission.status)
  } catch {
    // Probe failed - treat as not granted so we never park a prompt from select/restore.
    return false
  }
}

/**
 * Start the HexStrike loopback suite only when cyber.hexstrike is already allowed.
 * Returns true when startHexStrike ran. Ask / deny / probe failure skips start.
 */
export async function autostartHexStrikeIfGranted(): Promise<boolean> {
  const granted = await readHexStrikePermissionGranted()
  if (!granted) return false
  await startHexStrike()
  return true
}

export function hexStrikeSelectMessage(autoStarted: boolean): string {
  return autoStarted ? HEXSTRIKE_READY_MESSAGE : HEXSTRIKE_DEFER_START_MESSAGE
}
