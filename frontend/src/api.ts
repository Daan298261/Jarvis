export function getPrivateKey(): string {
  try {
    return localStorage.getItem("jarvis_private_key") || ""
  } catch {
    return ""
  }
}

export function setPrivateKey(key: string): void {
  try {
    if (key) {
      localStorage.setItem("jarvis_private_key", key.trim())
    } else {
      localStorage.removeItem("jarvis_private_key")
    }
  } catch {
    // ignore
  }
}

export function getAuthUrl(path: string): string {
  const key = getPrivateKey()
  if (!key) return path
  const sep = path.includes("?") ? "&" : "?"
  return `${path}${sep}key=${encodeURIComponent(key)}`
}

function authHeaders(extra?: HeadersInit): Record<string, string> {
  const headers: Record<string, string> = { ...(extra as Record<string, string> || {}) }
  const key = getPrivateKey()
  if (key && !headers["Authorization"] && !headers["X-Jarvis-Key"]) {
    headers["X-Jarvis-Key"] = key
  }
  return headers
}

async function throwIfNotOk(response: Response): Promise<void> {
  if (response.ok) return
  const text = await response.text()
  let errorDetail = text
  try {
    const parsed = JSON.parse(text)
    errorDetail = parsed.detail || text
  } catch {
    // not JSON
  }
  throw new Error(errorDetail || response.statusText)
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders({ "Content-Type": "application/json", ...(init?.headers as Record<string, string> || {}) })
  const response = await fetch(path, {
    ...init,
    headers,
  })
  await throwIfNotOk(response)
  return response.json() as Promise<T>
}

export async function apiForm<T>(path: string, body: FormData, init?: RequestInit): Promise<T> {
  const headers = authHeaders(init?.headers)
  const response = await fetch(path, {
    method: "POST",
    ...init,
    headers,
    body,
  })
  await throwIfNotOk(response)
  return response.json() as Promise<T>
}

export async function fetchAudio(path: string, init?: RequestInit): Promise<Blob> {
  const headers = authHeaders({ "Content-Type": "application/json", ...(init?.headers as Record<string, string> || {}) })
  const response = await fetch(path, { ...init, headers })
  await throwIfNotOk(response)
  return response.blob()
}

export type Task = {
  id: string
  title: string
  prompt: string
  status: string
  stage: string
  execution_mode?: string
  task_class?: string
  exposed_tools?: string[]
  acceptance_criteria?: string
  current_action: string
  current_tool: string
  result: string
  error: string
  verification?: string
  retries: number
  duration_seconds: number
  model_calls?: number
  tool_calls?: number
  schema_errors?: number
  model_ms?: number
  tool_ms?: number
  human_interventions?: number
  started_at?: string | null
  created_at: string
  waiting_for_confirmation: boolean
  events?: { kind: string; title: string; detail: string; stage: string; created_at: string }[]
}

export type SwarmNodeHardware = {
  os_name?: string
  os_version?: string
  architecture?: string
  cpu_name?: string
  cpu_cores?: number
  cpu_threads?: number
  ram_total_gb?: number
  ram_available_gb?: number
  gpu_name?: string | null
  vram_total_mib?: number | null
  vram_free_mib?: number | null
  nvidia_driver?: string | null
  cuda_version?: string | null
  disk_free_gb?: number
  disk_total_gb?: number
  python_version?: string
  node_installed?: boolean
  git_installed?: boolean
  docker_installed?: boolean
  office_installed?: boolean
  wsl_available?: boolean
}

export type SwarmNodeResources = {
  cpu_cores?: number
  cpu_threads?: number
  ram_total_gb?: number
  ram_available_gb?: number
  vram_total_mib?: number | null
  vram_free_mib?: number | null
  disk_total_gb?: number
  disk_free_gb?: number
  gpu_name?: string | null
}

export type SwarmWorker = {
  id: string
  name: string
  kind: string
  status: string
  node_id: string
}

export type SwarmNode = {
  id: string
  hostname?: string
  host_alias: string
  address: string
  status: string
  class: string
  roles: string[]
  is_local: boolean
  hardware: SwarmNodeHardware
  resources: SwarmNodeResources
  workers?: SwarmWorker[]
  created_at?: string | null
  updated_at?: string | null
  last_seen_at?: string | null
}

export type SwarmNodesResponse = {
  nodes: SwarmNode[]
}

export async function listSwarmNodes(): Promise<SwarmNodesResponse> {
  return api<SwarmNodesResponse>("/api/swarm/nodes")
}

export async function getSwarmNode(nodeId: string): Promise<SwarmNode> {
  return api<SwarmNode>(`/api/swarm/nodes/${encodeURIComponent(nodeId)}`)
}

export type SwarmRoleHolder = {
  role: string
  node_id: string
  hostname: string
  assignment: string
}

export type SwarmRolesResponse = {
  orchestrator: SwarmRoleHolder | null
  leader: SwarmRoleHolder | null
}

export async function listSwarmRoles(): Promise<SwarmRolesResponse> {
  return api<SwarmRolesResponse>("/api/swarm/roles")
}

export type SwarmRoleName = "orchestrator" | "leader"

export type SwarmRolePolicyLevel = "AUTO" | "PREFERRED" | "FORCED" | "AVOID" | "DISABLED"

export const SWARM_ROLE_NAMES: SwarmRoleName[] = ["orchestrator", "leader"]

export const SWARM_ROLE_POLICY_LEVELS: SwarmRolePolicyLevel[] = [
  "AUTO",
  "PREFERRED",
  "FORCED",
  "AVOID",
  "DISABLED",
]

export type SwarmRolePolicy = {
  node_id: string
  role: string
  policy: string
  updated_at: string | null
}

export type SwarmNodeRolePoliciesResponse = {
  node_id: string
  policies: SwarmRolePolicy[]
}

export async function getNodeRolePolicies(nodeId: string): Promise<SwarmNodeRolePoliciesResponse> {
  return api<SwarmNodeRolePoliciesResponse>(
    `/api/swarm/nodes/${encodeURIComponent(nodeId)}/role-policies`,
  )
}

export async function putNodeRolePolicy(
  nodeId: string,
  role: string,
  policy: string,
): Promise<SwarmRolePolicy> {
  return api<SwarmRolePolicy>(
    `/api/swarm/nodes/${encodeURIComponent(nodeId)}/role-policies/${encodeURIComponent(role)}`,
    {
      method: "PUT",
      body: JSON.stringify({ policy }),
    },
  )
}

export type SwarmBudgetPreset = "minimal" | "balanced" | "high" | "maximum" | "custom"

export type SwarmBudgetMode = "static" | "dynamic"

export type SwarmBudgetLimitCap = "HARD" | "SOFT"

export type SwarmBudgetLimit = {
  percent?: number
  cap?: SwarmBudgetLimitCap
}

export type SwarmBudgetLimits = {
  cpu?: SwarmBudgetLimit
  ram?: SwarmBudgetLimit
  gpu?: SwarmBudgetLimit
  vram?: SwarmBudgetLimit
  disk?: SwarmBudgetLimit
  network?: SwarmBudgetLimit
}

export type SwarmResourceAmounts = {
  cpu?: number
  ram?: number
  gpu?: number
  vram?: number
  disk?: number
  network?: number
}

export type SwarmNodeBudget = {
  node_id: string
  preset: SwarmBudgetPreset
  mode: SwarmBudgetMode
  global_percent: number
  limits: SwarmBudgetLimits
  updated_at: string | null
  effective?: SwarmResourceAmounts
  remaining?: SwarmResourceAmounts
}

export type SwarmBudgetUpdate = {
  preset?: SwarmBudgetPreset
  mode?: SwarmBudgetMode
  global_percent?: number
  limits?: SwarmBudgetLimits
}

export const SWARM_BUDGET_PRESETS: SwarmBudgetPreset[] = [
  "minimal",
  "balanced",
  "high",
  "maximum",
  "custom",
]

export async function getNodeBudget(nodeId: string): Promise<SwarmNodeBudget> {
  return api<SwarmNodeBudget>(`/api/swarm/nodes/${encodeURIComponent(nodeId)}/budget`)
}

export async function putNodeBudget(
  nodeId: string,
  body: SwarmBudgetUpdate,
): Promise<SwarmNodeBudget> {
  return api<SwarmNodeBudget>(`/api/swarm/nodes/${encodeURIComponent(nodeId)}/budget`, {
    method: "PUT",
    body: JSON.stringify(body),
  })
}

export type SwarmLeaseClaim = {
  cpu_threads?: number
  ram_gb?: number
  gpu_percent?: number
  vram_mib?: number
  disk_gb?: number
  network_mbps?: number
}

export type SwarmLeaseStatus = "active" | "released" | "expired"

export type SwarmLease = {
  id: string
  node_id: string
  claim: SwarmLeaseClaim
  status: SwarmLeaseStatus
  created_at: string | null
  expires_at: string | null
  released_at: string | null
}

export type SwarmNodeLeasesResponse = {
  node_id: string
  leases: SwarmLease[]
}

export type SwarmLeaseCreate = {
  claim: SwarmLeaseClaim
  ttl_seconds?: number
}

export async function listNodeLeases(nodeId: string): Promise<SwarmNodeLeasesResponse> {
  return api<SwarmNodeLeasesResponse>(`/api/swarm/nodes/${encodeURIComponent(nodeId)}/leases`)
}

export async function createNodeLease(
  nodeId: string,
  body: SwarmLeaseCreate,
): Promise<SwarmLease> {
  return api<SwarmLease>(`/api/swarm/nodes/${encodeURIComponent(nodeId)}/leases`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function releaseNodeLease(nodeId: string, leaseId: string): Promise<SwarmLease> {
  return api<SwarmLease>(
    `/api/swarm/nodes/${encodeURIComponent(nodeId)}/leases/${encodeURIComponent(leaseId)}`,
    { method: "DELETE" },
  )
}

export type SwarmPlacementRequest = {
  capabilities?: string[]
  role?: string
  worker_id?: string
  worker_kind?: string
  claim?: SwarmLeaseClaim
  ttl_seconds?: number
}

export type SwarmPlacementAccepted = {
  accepted: true
  node_id: string
  hostname?: string
  worker: SwarmWorker
  reason: string
  lease?: SwarmLease
}

export type SwarmPlacementRejected = {
  accepted: false
  code: string
  reason: string
}

export type SwarmPlacementResult = SwarmPlacementAccepted | SwarmPlacementRejected

export async function postSwarmPlacement(body: SwarmPlacementRequest): Promise<SwarmPlacementResult> {
  const headers = authHeaders({ "Content-Type": "application/json" })
  const response = await fetch("/api/swarm/placement", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  })
  if (response.status === 409) {
    return response.json() as Promise<SwarmPlacementRejected>
  }
  await throwIfNotOk(response)
  return response.json() as Promise<SwarmPlacementAccepted>
}

export type SwarmIntelligenceRequest = {
  prompt: string
  task_class?: string
  execution_mode?: string
}

export type SwarmIntelligenceResult = {
  task_class: string
  worker_kind: string
  capabilities: string[]
  worker_id?: string
  model?: string
}

export async function postSwarmIntelligence(
  body: SwarmIntelligenceRequest,
): Promise<SwarmIntelligenceResult> {
  return api<SwarmIntelligenceResult>("/api/swarm/intelligence", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export type SwarmDispatchRequest = {
  prompt: string
  task_class?: string
  execution_mode?: string
  role?: string
  claim?: SwarmLeaseClaim
  ttl_seconds?: number
}

export type SwarmDispatchResult = {
  intelligence: SwarmIntelligenceResult
  placement: SwarmPlacementResult
}

export async function postSwarmDispatch(body: SwarmDispatchRequest): Promise<SwarmDispatchResult> {
  const headers = authHeaders({ "Content-Type": "application/json" })
  const response = await fetch("/api/swarm/dispatch", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  })
  if (response.status === 409) {
    return response.json() as Promise<SwarmDispatchResult>
  }
  await throwIfNotOk(response)
  return response.json() as Promise<SwarmDispatchResult>
}

/* ---- Setup / diagnostics (RFC-0002) ---- */

export type SetupWizardStep =
  | "welcome"
  | "system"
  | "role"
  | "resources"
  | "inference"
  | "runtime"
  | "desktop"
  | "verification"
  | "done"

export type SetupState = {
  version: number
  completed: boolean
  current_step: SetupWizardStep
  completed_steps: string[]
  jarvis_role: string
  recommended_class: string
  role_policies: Record<string, string>
  resource_preset: string
  global_percent: number
  resource_mode: string
  resource_limits: Record<string, unknown>
  inference_choice: string
  inference_profile: string
  remote_host: string
  remote_port: number
  install_expert_27b: boolean
  install_playwright: boolean
  desktop_prefs: {
    start_with_windows?: boolean
    start_minimized?: boolean
    close_to_tray?: boolean
  }
  component_status: Record<string, unknown>
  last_error: string
  updated_at: string
}

export type SetupStatusResponse = {
  needs_setup: boolean
  state: SetupState
  steps: SetupWizardStep[]
  components: Record<string, ComponentInstallState>
}

export type ComponentInstallState = {
  id: string
  label: string
  status: string
  bytes_done: number
  bytes_total: number
  error: string
  path: string
  optional: boolean
  detail: string
}

export type SetupRecommendation = {
  recommended_class: string
  suitable_for: string[]
  capabilities: Record<string, boolean>
  role_policies: Record<string, string>
  resource_preset: string
  inference_default: string
  notes: string[]
  hardware_summary: Record<string, unknown>
}

export async function getSetupStatus(): Promise<SetupStatusResponse> {
  return api<SetupStatusResponse>("/api/setup/status")
}

export async function getSetupRecommend(): Promise<SetupRecommendation> {
  return api<SetupRecommendation>("/api/setup/recommend")
}

export async function putSetupState(body: Partial<SetupState>): Promise<{ state: SetupState }> {
  return api<{ state: SetupState }>("/api/setup/state", {
    method: "PUT",
    body: JSON.stringify(body),
  })
}

export async function advanceSetup(
  step: string,
  next_step?: string,
  patch?: Record<string, unknown>,
): Promise<{ state: SetupState }> {
  return api<{ state: SetupState }>("/api/setup/advance", {
    method: "POST",
    body: JSON.stringify({ step, next_step, patch: patch || {} }),
  })
}

export async function applySetup(): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>("/api/setup/apply", { method: "POST", body: "{}" })
}

export async function completeSetup(opts?: {
  apply?: boolean
  without_local_model?: boolean
}): Promise<{ ok: boolean; state: SetupState }> {
  return api<{ ok: boolean; state: SetupState }>("/api/setup/complete", {
    method: "POST",
    body: JSON.stringify(opts || { apply: true }),
  })
}

export async function installSetupComponent(component: string): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>("/api/setup/install", {
    method: "POST",
    body: JSON.stringify({ component }),
  })
}

export async function installSelectedComponents(): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>("/api/setup/install", {
    method: "POST",
    body: JSON.stringify({ all_selected: true }),
  })
}

export async function listSetupComponents(): Promise<{
  components: Record<string, ComponentInstallState>
  ids: string[]
}> {
  return api("/api/setup/components")
}

export async function getDiagnostics(): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>("/api/diagnostics")
}

export async function getDiagnosticsText(): Promise<{ text: string; diagnostics: Record<string, unknown> }> {
  return api("/api/diagnostics/text")
}
