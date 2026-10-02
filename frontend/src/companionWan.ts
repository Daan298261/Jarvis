export type WanMethod = "auto" | "upnp" | "ssh_reverse" | "gateway_ssh"

export type WanForm = {
  wan_method: WanMethod
  ssh_host: string
  ssh_port: string
  ssh_user: string
  ssh_identity_file: string
  gateway_host: string
  gateway_port: string
  gateway_user: string
  gateway_identity_file: string
  gateway_username: string
  gateway_password: string
  wan_public_host: string
}

export const EMPTY_WAN_FORM: WanForm = {
  wan_method: "auto",
  ssh_host: "",
  ssh_port: "22",
  ssh_user: "",
  ssh_identity_file: "",
  gateway_host: "",
  gateway_port: "22",
  gateway_user: "",
  gateway_identity_file: "",
  gateway_username: "",
  gateway_password: "",
  wan_public_host: "",
}

const STRING_FIELDS = [
  "ssh_host",
  "ssh_user",
  "ssh_identity_file",
  "gateway_host",
  "gateway_user",
  "gateway_identity_file",
  "gateway_username",
  "wan_public_host",
] as const

const PORT_FIELDS = ["ssh_port", "gateway_port"] as const

export function wanFormFromSnapshot(snapshot: Record<string, unknown> | null | undefined): WanForm {
  const wan = (snapshot?.wan && typeof snapshot.wan === "object" ? snapshot.wan : {}) as Record<string, unknown>
  const method = String(wan.wan_method || "auto")
  return {
    ...EMPTY_WAN_FORM,
    wan_method: method === "upnp" || method === "ssh_reverse" || method === "gateway_ssh" ? method : "auto",
    ssh_host: String(wan.ssh_host || ""),
    ssh_port: String(wan.ssh_port || "22"),
    ssh_user: String(wan.ssh_user || ""),
    ssh_identity_file: String(wan.ssh_identity_file || ""),
    gateway_host: String(wan.gateway_host || ""),
    gateway_port: String(wan.gateway_port || "22"),
    gateway_user: String(wan.gateway_user || ""),
    gateway_identity_file: String(wan.gateway_identity_file || ""),
    gateway_username: String(wan.gateway_username || ""),
    wan_public_host: String(wan.wan_public_host || ""),
  }
}

export function connectionPrepareBody(
  enabled: boolean,
  remote: boolean,
  form: WanForm,
): Record<string, unknown> {
  const body: Record<string, unknown> = { enabled, remote }
  if (!enabled || !remote) return body
  body.wan_method = form.wan_method
  for (const key of STRING_FIELDS) {
    const value = form[key].trim()
    if (value) body[key] = value
  }
  for (const key of PORT_FIELDS) {
    const value = form[key].trim()
    if (value) body[key] = Number(value)
  }
  const password = form.gateway_password.trim()
  if (password) body.gateway_password = password
  return body
}

export function wanPathLabel(path: string | undefined, router: string | undefined): string {
  if (path === "upnp") return "Router mapped with UPnP (TCP 4781, one-hour lease)"
  if (path === "gateway_ssh") return "Router mapped over gateway SSH (TCP 4781)"
  if (path === "ssh_reverse" || router === "tunneled") return "SSH reverse tunnel to your host (TCP 4781)"
  if (router === "mapped") return "Router mapped for companion TLS (TCP 4781)"
  return ""
}
