/**
 * Pairing panel recovery helpers (pairing-stability fix 4).
 *
 * When the core backend is down the pairing panel cannot fetch a code. It now
 * retries with backoff and asks the loopback ANZU Manager (:4782) why the core
 * is down, offering a Restart. Pure helpers live here so they are unit-testable.
 */

export const MANAGER_ORIGIN = "http://127.0.0.1:4782"

const RETRY_STEPS_MS = [2000, 4000, 8000, 15000, 30000]

/** Delay before retry N (0-based): 2s, 4s, 8s, 15s, then every 30s. */
export function pairingRetryDelayMs(attempt: number): number {
  const index = Math.max(0, Math.min(Math.floor(attempt), RETRY_STEPS_MS.length - 1))
  return RETRY_STEPS_MS[index]
}

export type ManagerCoreState = "ready" | "starting" | "stopped"

export type ManagerSupervisor = {
  enabled: boolean
  desired_running: boolean
  restarting: boolean
  restart_attempts: number
  next_restart_in_seconds: number
  last_exit: { reason?: string; at?: number; error_tail?: string[]; crash_log?: string | null; launch_error?: string } | null
}

export type ManagerStatus = {
  core: { state: ManagerCoreState; healthy: boolean; process_present: boolean }
  supervisor?: ManagerSupervisor
}

export type ManagerView =
  | { kind: "unreachable" }
  | { kind: "status"; status: ManagerStatus }

/** Human summary of why pairing is unavailable, from the manager snapshot. */
export function describeManagerView(view: ManagerView | null): string {
  if (!view) return "Checking ANZU Manager…"
  if (view.kind === "unreachable") {
    return "ANZU backend is not answering and ANZU Manager is not running. Start ANZU from the Start menu or tray."
  }
  const { core, supervisor } = view.status
  if (core.state === "ready") return "ANZU backend is back. Loading pairing code…"
  const reason = supervisor?.last_exit?.reason
  if (supervisor?.restarting) return "ANZU Manager is restarting the backend…"
  if (core.state === "starting") return "ANZU backend is starting…"
  if (supervisor?.enabled && supervisor.desired_running) {
    const wait = supervisor.next_restart_in_seconds
    const when = wait > 0 ? `Automatic restart in ${wait}s.` : "Automatic restart is pending."
    return reason ? `ANZU backend stopped (${reason}). ${when}` : `ANZU backend is stopped. ${when}`
  }
  return reason ? `ANZU backend stopped (${reason}).` : "ANZU backend is stopped."
}

export async function fetchManagerStatus(fetchImpl: typeof fetch = fetch): Promise<ManagerView> {
  try {
    const response = await fetchImpl(`${MANAGER_ORIGIN}/api/manager/v1/status`, { cache: "no-store" })
    if (!response.ok) return { kind: "unreachable" }
    return { kind: "status", status: (await response.json()) as ManagerStatus }
  } catch {
    return { kind: "unreachable" }
  }
}

export async function requestManagerRestart(fetchImpl: typeof fetch = fetch): Promise<{ ok: boolean; message: string }> {
  try {
    const response = await fetchImpl(`${MANAGER_ORIGIN}/api/manager/v1/control/restart`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    })
    const data = (await response.json().catch(() => ({}))) as { ok?: boolean; detail?: string }
    if (!response.ok) return { ok: false, message: data.detail || `Restart failed (${response.status}).` }
    return data.ok
      ? { ok: true, message: "ANZU backend restarted." }
      : { ok: false, message: "Restart was sent but the backend is not healthy yet." }
  } catch {
    return { ok: false, message: "ANZU Manager is not reachable on this computer." }
  }
}
