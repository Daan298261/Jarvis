/** RFC-0215 — off-LAN companion access over Tailscale only: pure helpers for the pairing panel. */

export type EndpointKind = "lan" | "tailscale"

export type TailscaleStatus = {
  installed: boolean
  running: boolean
  backend_state: string
  dns_name: string
  ips: string[]
  hint: string
}

export type ReachabilityResult = { url: string; kind: EndpointKind; status: string; detail: string }

export type RemoteSnapshot = {
  remote?: boolean
  tailscale_enabled?: boolean
  endpoints?: string[]
  tailscale?: TailscaleStatus
  reachability?: ReachabilityResult[]
  exposure?: string
}

export type RemoteForm = { remote: boolean; tailscale: boolean }

export function remoteFormFromSnapshot(snapshot: RemoteSnapshot | null | undefined): RemoteForm {
  return { remote: Boolean(snapshot?.remote), tailscale: snapshot?.tailscale_enabled !== false }
}

/** Body for POST /api/mobile/manage/connection — the single remote-access control. */
export function remoteConnectionBody(form: RemoteForm): Record<string, unknown> {
  const body: Record<string, unknown> = { enabled: true, remote: form.remote }
  if (form.remote) body.tailscale = form.tailscale
  return body
}

export function tailscaleGuide(status: TailscaleStatus | undefined): string {
  if (!status) return "Turn on remote access to check for Tailscale."
  if (!status.installed)
    return "Tailscale is not installed on this PC. Install it from tailscale.com/download, sign in, install the Tailscale app on your phone with the same account, then press Refresh."
  if (!status.running) return status.hint || "Tailscale is installed but not connected. Open Tailscale and sign in."
  return `Tailscale connected as ${status.dns_name || status.ips[0] || "this PC"}. Keep Tailscale on in the phone app to reach ANZU from anywhere.`
}

export function kindLabel(kind: EndpointKind): string {
  return kind === "tailscale" ? "Tailscale" : "Home network"
}

export function reachabilityLabel(result: ReachabilityResult): string {
  return result.status === "ok" ? "reachable from this PC" : "failed"
}
