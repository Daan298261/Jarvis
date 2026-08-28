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

export const RUNTIME_PRIVACY_CLASSES = ["local-only", "trusted-remote", "public-remote"] as const
export type RuntimePrivacyClass = (typeof RUNTIME_PRIVACY_CLASSES)[number]

export const RUNTIME_SELECT_MODES = ["prefer", "force"] as const
export type RuntimeSelectMode = (typeof RUNTIME_SELECT_MODES)[number]

export const RUNTIME_PROFILE_PROVIDERS = [
  "openai-compat",
  "local-llama",
  "ollama",
  "lmstudio",
  "vllm",
  "sglang",
  "anthropic",
  "google",
] as const

export type RuntimeProfile = {
  id: string
  name: string
  label: string
  model: string
  provider: string
  endpoint: string
  context_limit: number
  quantization: string
  privacy_class: string
  cost_ceiling_usd: number | null
  capability_tags: string[]
  model_profile: string | null
  specialization_tags: string[]
  is_local: boolean
  description: string
}

export type RuntimeProfileIn = {
  name: string
  label?: string | null
  model: string
  provider?: string
  endpoint: string
  context_limit?: number
  quantization?: string
  privacy_class?: string
  cost_ceiling_usd?: number | null
  capability_tags?: string[]
  model_profile?: string | null
  specialization_tags?: string[]
  is_local?: boolean
  description?: string
}

export type RuntimeProfileUpdate = {
  label?: string | null
  model?: string | null
  provider?: string | null
  endpoint?: string | null
  context_limit?: number | null
  quantization?: string | null
  privacy_class?: string | null
  cost_ceiling_usd?: number | null
  capability_tags?: string[] | null
  model_profile?: string | null
  specialization_tags?: string[] | null
  is_local?: boolean | null
  description?: string | null
}

export type RuntimeProfilesListResponse = {
  profiles: RuntimeProfile[]
  policies: string[]
}

export type RuntimeRouteRequest = {
  preferred_profiles?: string[]
  forbidden_profiles?: string[]
  force_profile?: string | null
  policy?: string
  required_capabilities?: string[]
  task_specialization?: string | null
  privacy_floor?: string
  max_cost_usd?: number | null
  warm_models?: string[]
  node_id?: string
  load_factor?: number
}

export type RuntimeRouteDecision = {
  accepted: boolean
  reason: string
  code: string
  alternatives?: unknown[]
  runtime_profile?: RuntimeProfile
  node?: {
    node_id: string
    hostname: string
    is_local: boolean
    warm_models: string[]
    load_factor: number
    hardware_fit: number
  }
  score?: {
    total: number
    expected_success: number
    latency: number
    cost: number
    privacy: number
    load: number
    network: number
    warm_bonus: number
    specialization_bonus: number
    preferred_bonus: number
    reasons: string[]
  }
}

const SELECTED_RUNTIME_KEY = "jarvis_selected_runtime_profile"
const SELECTED_RUNTIME_MODE_KEY = "jarvis_selected_runtime_mode"
const SELECTED_RUNTIME_POLICY_KEY = "jarvis_selected_runtime_policy"

export function getSelectedRuntimeProfileId(): string {
  try {
    return localStorage.getItem(SELECTED_RUNTIME_KEY) || ""
  } catch {
    return ""
  }
}

export function setSelectedRuntimeProfileId(id: string): void {
  try {
    if (id) localStorage.setItem(SELECTED_RUNTIME_KEY, id)
    else localStorage.removeItem(SELECTED_RUNTIME_KEY)
  } catch {
    // ignore
  }
}

export function getSelectedRuntimeMode(): RuntimeSelectMode {
  try {
    const value = localStorage.getItem(SELECTED_RUNTIME_MODE_KEY)
    if (value === "force") return "force"
  } catch {
    // ignore
  }
  return "prefer"
}

export function setSelectedRuntimeMode(mode: RuntimeSelectMode): void {
  try {
    localStorage.setItem(SELECTED_RUNTIME_MODE_KEY, mode)
  } catch {
    // ignore
  }
}

export function getSelectedRuntimePolicy(): string {
  try {
    return localStorage.getItem(SELECTED_RUNTIME_POLICY_KEY) || "local-first"
  } catch {
    return "local-first"
  }
}

export function setSelectedRuntimePolicy(policy: string): void {
  try {
    if (policy) localStorage.setItem(SELECTED_RUNTIME_POLICY_KEY, policy)
    else localStorage.removeItem(SELECTED_RUNTIME_POLICY_KEY)
  } catch {
    // ignore
  }
}

export async function listRuntimeProfiles(): Promise<RuntimeProfilesListResponse> {
  return api<RuntimeProfilesListResponse>("/api/runtime-profiles")
}

export async function getRuntimeProfile(profileId: string): Promise<RuntimeProfile> {
  return api<RuntimeProfile>(`/api/runtime-profiles/${encodeURIComponent(profileId)}`)
}

export async function createRuntimeProfile(body: RuntimeProfileIn): Promise<RuntimeProfile> {
  return api<RuntimeProfile>("/api/runtime-profiles", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function updateRuntimeProfile(
  profileId: string,
  body: RuntimeProfileUpdate,
): Promise<RuntimeProfile> {
  return api<RuntimeProfile>(`/api/runtime-profiles/${encodeURIComponent(profileId)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  })
}

export async function deleteRuntimeProfile(profileId: string): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>(`/api/runtime-profiles/${encodeURIComponent(profileId)}`, {
    method: "DELETE",
  })
}

export async function resetRuntimeProfiles(): Promise<{ profiles: RuntimeProfile[] }> {
  return api<{ profiles: RuntimeProfile[] }>("/api/runtime-profiles/reset", { method: "POST" })
}

export async function previewRuntimeRoute(body: RuntimeRouteRequest): Promise<RuntimeRouteDecision> {
  return api<RuntimeRouteDecision>("/api/runtime-profiles/route/preview", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function routeRuntime(body: RuntimeRouteRequest): Promise<RuntimeRouteDecision> {
  return api<RuntimeRouteDecision>("/api/runtime-profiles/route", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export const PERSISTENCE_MODES = ["ONE_SHOT", "UNTIL_COMPLETE", "CONTINUOUS"] as const
export type PersistenceMode = (typeof PERSISTENCE_MODES)[number]

export const PROACTIVITY_MODES = [
  "DISABLED",
  "SUGGEST_ONLY",
  "CREATE_TASKS",
  "EXECUTE_WITHIN_POLICY",
] as const
export type ProactivityMode = (typeof PROACTIVITY_MODES)[number]

export type AwayModeState = {
  enabled: boolean
  pause_proactivity: boolean
  message: string
  updated_at?: string
}

export type AwayModeUpdate = {
  enabled?: boolean
  pause_proactivity?: boolean
  message?: string
}

export type EffectiveBehavior = {
  persistence: string
  configured_proactivity: string
  effective_proactivity: string
  away_mode: AwayModeState
  can_suggest: boolean
  can_create_tasks: boolean
  can_execute_within_policy: boolean
  requires_approval_for_execution: boolean
}

export type AutonomyProfile = {
  id: string
  name: string
  persistence: string
  proactivity: string
  agent_id: string
  created_at: string
  updated_at: string
  metadata: Record<string, unknown>
  effective?: EffectiveBehavior
}

export type AutonomyProfileIn = {
  name: string
  persistence?: string
  proactivity?: string
  agent_id?: string
  metadata?: Record<string, unknown>
}

export type AutonomyProfileUpdate = {
  name?: string
  persistence?: string
  proactivity?: string
  agent_id?: string
  metadata?: Record<string, unknown>
}

export type AutonomyModes = {
  persistence_modes: string[]
  proactivity_modes: string[]
}

export type EffectiveProactivityRow = {
  configured: string
  effective: string
  away_mode_active: boolean
}

export type ProactiveAction = {
  id: string
  parent_agent_id: string
  trigger: string
  evidence: Record<string, unknown>
  rationale: string
  budget: Record<string, unknown>
  proactivity: string
  persistence: string
  status: string
  requires_approval: boolean
  created_at: string
  approved_at?: string | null
  executed_at?: string | null
  capability?: string
  node_id?: string
}

export async function listAutonomyModes(): Promise<AutonomyModes> {
  return api<AutonomyModes>("/api/autonomy/modes")
}

export async function listAutonomyProfiles(): Promise<{ profiles: AutonomyProfile[] }> {
  return api<{ profiles: AutonomyProfile[] }>("/api/autonomy/profiles")
}

export async function createAutonomyProfile(body: AutonomyProfileIn): Promise<AutonomyProfile> {
  return api<AutonomyProfile>("/api/autonomy/profiles", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function getAutonomyProfile(profileId: string): Promise<AutonomyProfile> {
  return api<AutonomyProfile>(`/api/autonomy/profiles/${encodeURIComponent(profileId)}`)
}

export async function updateAutonomyProfile(
  profileId: string,
  body: AutonomyProfileUpdate,
): Promise<AutonomyProfile> {
  return api<AutonomyProfile>(`/api/autonomy/profiles/${encodeURIComponent(profileId)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  })
}

export async function getAutonomyProfileEffective(profileId: string): Promise<EffectiveBehavior> {
  return api<EffectiveBehavior>(`/api/autonomy/profiles/${encodeURIComponent(profileId)}/effective`)
}

export async function getAwayMode(): Promise<AwayModeState> {
  return api<AwayModeState>("/api/autonomy/away-mode")
}

export async function putAwayMode(body: AwayModeUpdate): Promise<AwayModeState> {
  return api<AwayModeState>("/api/autonomy/away-mode", {
    method: "PUT",
    body: JSON.stringify(body),
  })
}

export async function listProactiveActions(parentAgentId?: string): Promise<{ actions: ProactiveAction[] }> {
  const query = parentAgentId ? `?parent_agent_id=${encodeURIComponent(parentAgentId)}` : ""
  return api<{ actions: ProactiveAction[] }>(`/api/autonomy/proactive${query}`)
}

export async function approveProactiveAction(actionId: string): Promise<ProactiveAction> {
  return api<ProactiveAction>(`/api/autonomy/proactive/${encodeURIComponent(actionId)}/approve`, {
    method: "POST",
  })
}

export async function getEffectiveProactivityMatrix(): Promise<{ rows: EffectiveProactivityRow[] }> {
  return api<{ rows: EffectiveProactivityRow[] }>("/api/autonomy/matrix/effective-proactivity")
}
