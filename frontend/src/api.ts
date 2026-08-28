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

function formatApiDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => formatApiDetail(item, "")).filter(Boolean)
    return parts.length ? parts.join("; ") : fallback
  }
  if (detail && typeof detail === "object") {
    const record = detail as { message?: unknown; code?: unknown; detail?: unknown; msg?: unknown }
    if (typeof record.msg === "string" && record.msg) return record.msg
    if (typeof record.message === "string" && record.message) return record.message
    if (typeof record.detail === "string" && record.detail) return record.detail
    if (typeof record.code === "string" && record.code) return record.code
    try {
      return JSON.stringify(detail)
    } catch {
      return fallback
    }
  }
  return fallback
}

async function throwIfNotOk(response: Response): Promise<void> {
  if (response.ok) return
  const text = await response.text()
  let errorDetail = text
  try {
    const parsed = JSON.parse(text)
    errorDetail = formatApiDetail(parsed.detail, text)
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
  autonomy?: string
  execution_mode?: string
  task_class?: string
  exposed_tools?: string[]
  allowed_tools?: string[]
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

export const AGENT_AUTONOMY_LEVELS = [
  "L0_OBSERVE",
  "L1_SUGGEST",
  "L2_EXECUTE_SAFE",
  "L3_EXECUTE_WITH_GATES",
  "L4_AUTONOMOUS",
  "L5_OPERATOR",
] as const

export type AgentAutonomyLevel = (typeof AGENT_AUTONOMY_LEVELS)[number]

export type InterviewAnswers = {
  mission: string
  success_criteria: string
  tone: string
  allowed_channels: string[]
  approval_required_actions: string[]
  budgets: Record<string, unknown>
  privacy: Record<string, unknown>
  scheduling: Record<string, unknown>
  escalation: Record<string, unknown>
  hard_prohibitions: string[]
  default_autonomy: string | null
}

export type AgentPolicyDocument = {
  autonomy?: Record<string, string>
  approval_required_actions?: string[]
  budgets?: Record<string, unknown>
  privacy?: Record<string, unknown>
  scheduling?: Record<string, unknown>
  escalation?: Record<string, unknown>
  channels?: string[]
  hard_prohibitions?: string[]
  [key: string]: unknown
}

export type AgentPolicyProfile = {
  id: string
  name: string
  interview_answers: InterviewAnswers
  policy: AgentPolicyDocument
  generated_prompt: string
  created_at: string
  updated_at: string
}

export type AgentPolicyProfileIn = {
  name: string
  interview_answers: InterviewAnswers
  policy?: AgentPolicyDocument | null
  generated_prompt?: string | null
  actor?: string
}

export type AgentPolicyProfileUpdate = {
  name?: string | null
  interview_answers?: InterviewAnswers | null
  policy?: AgentPolicyDocument | null
  generated_prompt?: string | null
  actor?: string
}

export type PlatformAgentPolicy = {
  autonomy_caps: Record<string, string>
  default_agent_autonomy: string
}

export type PlatformAgentPolicyUpdate = {
  autonomy_caps?: Record<string, string> | null
  default_agent_autonomy?: string | null
  actor?: string
}

export type AgentPolicyAuditEvent = {
  id: string
  actor: string
  profile_id: string | null
  field: string
  old_value: unknown
  new_value: unknown
  timestamp: string
}

export function emptyInterviewAnswers(): InterviewAnswers {
  return {
    mission: "",
    success_criteria: "",
    tone: "professional",
    allowed_channels: [],
    approval_required_actions: [],
    budgets: {},
    privacy: {},
    scheduling: {},
    escalation: {},
    hard_prohibitions: [],
    default_autonomy: "L2_EXECUTE_SAFE",
  }
}

export async function listAgentPolicyProfiles(): Promise<{ profiles: AgentPolicyProfile[] }> {
  return api<{ profiles: AgentPolicyProfile[] }>("/api/agent-policy")
}

export async function createAgentPolicyProfile(body: AgentPolicyProfileIn): Promise<AgentPolicyProfile> {
  return api<AgentPolicyProfile>("/api/agent-policy", {
    method: "POST",
    body: JSON.stringify({ actor: "portal", ...body }),
  })
}

export async function getAgentPolicyProfile(profileId: string): Promise<AgentPolicyProfile> {
  return api<AgentPolicyProfile>(`/api/agent-policy/${encodeURIComponent(profileId)}`)
}

export async function updateAgentPolicyProfile(
  profileId: string,
  body: AgentPolicyProfileUpdate,
): Promise<AgentPolicyProfile> {
  return api<AgentPolicyProfile>(`/api/agent-policy/${encodeURIComponent(profileId)}`, {
    method: "PUT",
    body: JSON.stringify({ actor: "portal", ...body }),
  })
}

export async function deleteAgentPolicyProfile(profileId: string): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>(
    `/api/agent-policy/${encodeURIComponent(profileId)}?actor=${encodeURIComponent("portal")}`,
    { method: "DELETE" },
  )
}

export async function normalizeInterviewAnswers(
  answers: InterviewAnswers,
): Promise<{ policy: AgentPolicyDocument }> {
  return api<{ policy: AgentPolicyDocument }>("/api/agent-policy/normalize", {
    method: "POST",
    body: JSON.stringify(answers),
  })
}

export async function getPlatformAgentPolicy(): Promise<PlatformAgentPolicy> {
  return api<PlatformAgentPolicy>("/api/agent-policy/platform")
}

export async function putPlatformAgentPolicy(
  body: PlatformAgentPolicyUpdate,
): Promise<PlatformAgentPolicy> {
  return api<PlatformAgentPolicy>("/api/agent-policy/platform", {
    method: "PUT",
    body: JSON.stringify({ actor: "portal", ...body }),
  })
}

export async function listAgentPolicyAudit(options?: {
  profileId?: string
  limit?: number
}): Promise<{ events: AgentPolicyAuditEvent[] }> {
  const params = new URLSearchParams()
  if (options?.profileId) params.set("profile_id", options.profileId)
  if (options?.limit != null) params.set("limit", String(options.limit))
  const query = params.toString()
  return api<{ events: AgentPolicyAuditEvent[] }>(`/api/agent-policy/audit${query ? `?${query}` : ""}`)
}

export const GUEST_RESOURCE_TYPES = ["task", "agent", "project", "decision_inbox"] as const
export type GuestResourceType = (typeof GUEST_RESOURCE_TYPES)[number]

export const GUEST_ACTIONS = ["read", "query", "approve"] as const
export type GuestAction = (typeof GUEST_ACTIONS)[number]

export type GuestGrant = {
  resource_type: GuestResourceType | string
  resource_id: string
  actions: string[]
}

export type GuestPortalLimits = {
  single_use: boolean
  max_sessions: number | null
  max_uses: number | null
}

export type GuestEffectivePermissions = {
  grants: GuestGrant[]
  denied_capabilities: string[]
  allowed_actions_summary: Record<string, string[]>
  limits: GuestPortalLimits
  expires_at: string | null
}

export type GuestPortalPreviewIn = {
  grants: GuestGrant[]
  limits?: Partial<GuestPortalLimits>
  expires_at?: string | null
}

export type GuestPortalCreateIn = GuestPortalPreviewIn & {
  label: string
  guest_label: string
}

export type GuestPortal = {
  id: string
  label: string
  guest_label: string
  scope: { grants: GuestGrant[] }
  limits: GuestPortalLimits
  created_at: string
  expires_at: string | null
  revoked: boolean
  revoked_at: string | null
  uses_remaining: number | null
  active_sessions: number
  token?: string
  effective_permissions?: GuestEffectivePermissions
}

export type GuestAuditEntry = {
  id: string
  portal_id: string
  session_id: string
  guest_label: string
  action: string
  resource_type: string | null
  resource_id: string | null
  path: string | null
  outcome: string
  detail: string | null
  created_at: string
}

export type GuestSession = {
  session_id: string
  guest_label: string
  portal_id: string
  effective_permissions: GuestEffectivePermissions
}

export type GuestTask = {
  id: string
  title: string
  status: string
  stage: string
  result: string
  error: string
  waiting_for_confirmation: boolean
  confirmation_payload?: unknown
  created_at: string | null
  updated_at: string | null
  finished_at: string | null
}

export type GuestTaskEvents = {
  task_id: string
  events: {
    kind: string
    title: string
    detail: string
    stage: string
    created_at: string | null
  }[]
}

export type GuestDecision = {
  id: string
  status: string
  detail: string
}

const GUEST_TOKEN_KEY = "jarvis_guest_token"
const GUEST_SESSION_KEY = "jarvis_guest_session"

export function getGuestToken(): string {
  try {
    return sessionStorage.getItem(GUEST_TOKEN_KEY) || ""
  } catch {
    return ""
  }
}

export function setGuestToken(token: string): void {
  try {
    const trimmed = token.trim()
    if (trimmed) sessionStorage.setItem(GUEST_TOKEN_KEY, trimmed)
    else sessionStorage.removeItem(GUEST_TOKEN_KEY)
  } catch {
    // ignore
  }
}

export function getGuestSessionId(): string {
  try {
    return sessionStorage.getItem(GUEST_SESSION_KEY) || ""
  } catch {
    return ""
  }
}

export function setGuestSessionId(id: string): void {
  try {
    const trimmed = id.trim()
    if (trimmed) sessionStorage.setItem(GUEST_SESSION_KEY, trimmed)
    else sessionStorage.removeItem(GUEST_SESSION_KEY)
  } catch {
    // ignore
  }
}

export function clearGuestSession(): void {
  setGuestToken("")
  setGuestSessionId("")
}

function guestAuthHeaders(extra?: HeadersInit): Record<string, string> {
  const headers: Record<string, string> = { ...(extra as Record<string, string> || {}) }
  const token = getGuestToken()
  if (token) {
    if (!headers["Authorization"] && !headers["authorization"]) {
      headers["Authorization"] = `Bearer ${token}`
    }
    if (!headers["X-Jarvis-Guest-Token"]) {
      headers["X-Jarvis-Guest-Token"] = token
    }
  }
  const sessionId = getGuestSessionId()
  if (sessionId && !headers["X-Jarvis-Guest-Session"]) {
    headers["X-Jarvis-Guest-Session"] = sessionId
  }
  return headers
}

async function guestApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = guestAuthHeaders({
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> || {}),
  })
  const response = await fetch(path, { ...init, headers })
  await throwIfNotOk(response)
  return response.json() as Promise<T>
}

export async function previewGuestPortal(body: GuestPortalPreviewIn): Promise<GuestEffectivePermissions> {
  return api<GuestEffectivePermissions>("/api/guest-portals/preview", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function createGuestPortal(body: GuestPortalCreateIn): Promise<GuestPortal> {
  return api<GuestPortal>("/api/guest-portals", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function listGuestPortals(): Promise<GuestPortal[]> {
  return api<GuestPortal[]>("/api/guest-portals")
}

export async function getGuestPortal(portalId: string): Promise<GuestPortal> {
  return api<GuestPortal>(`/api/guest-portals/${encodeURIComponent(portalId)}`)
}

export async function revokeGuestPortal(portalId: string): Promise<GuestPortal> {
  return api<GuestPortal>(`/api/guest-portals/${encodeURIComponent(portalId)}/revoke`, {
    method: "POST",
  })
}

export async function listGuestPortalAudit(portalId: string, limit = 200): Promise<GuestAuditEntry[]> {
  const query = limit != null ? `?limit=${encodeURIComponent(String(limit))}` : ""
  return api<GuestAuditEntry[]>(`/api/guest-portals/${encodeURIComponent(portalId)}/audit${query}`)
}

export async function startGuestSession(): Promise<GuestSession> {
  const session = await guestApi<GuestSession>("/api/guest/session", { method: "POST" })
  if (session.session_id) setGuestSessionId(session.session_id)
  return session
}

export async function getGuestSession(): Promise<GuestSession> {
  return guestApi<GuestSession>("/api/guest/session")
}

export async function getGuestTask(taskId: string): Promise<GuestTask> {
  return guestApi<GuestTask>(`/api/guest/tasks/${encodeURIComponent(taskId)}`)
}

export async function getGuestTaskEvents(taskId: string): Promise<GuestTaskEvents> {
  return guestApi<GuestTaskEvents>(`/api/guest/tasks/${encodeURIComponent(taskId)}/events`)
}

export async function approveGuestTask(taskId: string): Promise<GuestTask> {
  return guestApi<GuestTask>(`/api/guest/tasks/${encodeURIComponent(taskId)}/approve`, {
    method: "POST",
    body: JSON.stringify({}),
  })
}

export async function getGuestDecision(decisionId: string): Promise<GuestDecision> {
  return guestApi<GuestDecision>(`/api/guest/decisions/${encodeURIComponent(decisionId)}`)
}

export class PackApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = "PackApiError"
    this.status = status
  }
}

export function formatPackError(err: unknown): string {
  if (err instanceof PackApiError) {
    if (err.status === 409) return `Conflict: ${err.message}`
    if (err.status === 400) return err.message
    if (err.status === 404) return err.message
    return err.message
  }
  if (err instanceof Error) return err.message
  return "Something went wrong with this pack."
}

export type PackManifestObject = Record<string, unknown>

export type PackPreviewAction = "install" | "upgrade" | "uninstall"

export type PackResourceChange = {
  resource_id: string
  resource_type: string
  action: "create" | "update" | "skip" | "conflict" | "delete" | string
  before?: Record<string, unknown> | null
  after?: Record<string, unknown> | null
  reason?: string
}

export type PackPreview = {
  pack_id: string
  version: string
  action: PackPreviewAction | string
  valid: boolean
  errors: string[]
  warnings: string[]
  changes: PackResourceChange[]
  trust: Record<string, unknown>
  capabilities: Record<string, unknown>
  dependencies: Record<string, unknown>
}

export type InstalledPack = {
  id: string
  name: string
  version: string
  description?: string
  status: string
  installed_at: string
  manifest_hash?: string
  previous_version?: string | null
  snapshot_id?: string | null
  resource_ids?: string[]
}

export type PackResourceRecord = {
  resource_id: string
  pack_id: string
  resource_type: string
  user_modified: boolean
  override?: string | null
  data_hash?: string
  installed_version?: string
  data: Record<string, unknown>
}

export type PackDetail = {
  installation: InstalledPack
  resources: PackResourceRecord[]
}

export type PackApplyResult = {
  installation: InstalledPack
  preview?: PackPreview
  snapshot_id?: string
}

export type PackUninstallResult = {
  pack_id: string
  removed_resources: string[]
  kept_resources: string[]
  preview?: PackPreview
}

export type PackRollbackResult = {
  installation: InstalledPack
  snapshot_id?: string
  resources?: string[]
}

export type PackHistoryEvent = {
  id: string
  event: string
  pack_id: string
  version?: string | null
  snapshot_id?: string | null
  timestamp: string
  details?: Record<string, unknown>
}

export type PackPreviewRequest = {
  manifest: PackManifestObject
  action?: PackPreviewAction
  overrides?: Record<string, string>
  require_signature?: boolean
}

export type PackInstallRequest = {
  manifest: PackManifestObject
  overrides?: Record<string, string>
  require_signature?: boolean
  enforce_policies?: boolean
}

export type PackExportRequest = {
  pack_id: string
  include_user_modifications?: boolean
  name?: string
  version?: string
  description?: string
}

async function packApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders({
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  })
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const text = await response.text()
    let message = text || response.statusText
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      message = formatApiDetail(parsed.detail, message)
    } catch {
      // keep text
    }
    throw new PackApiError(message || response.statusText, response.status)
  }
  return response.json() as Promise<T>
}

export async function listPacks(): Promise<{ packs: InstalledPack[] }> {
  return packApi<{ packs: InstalledPack[] }>("/api/packs")
}

export async function getPack(packId: string): Promise<PackDetail> {
  return packApi<PackDetail>(`/api/packs/${encodeURIComponent(packId)}`)
}

export async function listPackHistory(): Promise<{ events: PackHistoryEvent[] }> {
  return packApi<{ events: PackHistoryEvent[] }>("/api/packs/history")
}

export async function listPackTrust(): Promise<{ key_ids: string[] }> {
  return packApi<{ key_ids: string[] }>("/api/packs/trust")
}

export async function addPackTrustKey(keyId: string, secret: string): Promise<{ key_ids: string[] }> {
  return packApi<{ key_ids: string[] }>("/api/packs/trust", {
    method: "POST",
    body: JSON.stringify({ key_id: keyId, secret }),
  })
}

export async function previewPack(body: PackPreviewRequest): Promise<PackPreview> {
  return packApi<PackPreview>("/api/packs/preview", {
    method: "POST",
    body: JSON.stringify({
      manifest: body.manifest,
      action: body.action ?? "install",
      overrides: body.overrides ?? {},
      require_signature: Boolean(body.require_signature),
    }),
  })
}

export async function installPack(body: PackInstallRequest): Promise<PackApplyResult> {
  return packApi<PackApplyResult>("/api/packs/install", {
    method: "POST",
    body: JSON.stringify({
      manifest: body.manifest,
      overrides: body.overrides ?? {},
      require_signature: Boolean(body.require_signature),
      enforce_policies: body.enforce_policies !== false,
    }),
  })
}

export async function upgradePack(body: PackInstallRequest): Promise<PackApplyResult> {
  return packApi<PackApplyResult>("/api/packs/upgrade", {
    method: "POST",
    body: JSON.stringify({
      manifest: body.manifest,
      overrides: body.overrides ?? {},
      require_signature: Boolean(body.require_signature),
      enforce_policies: body.enforce_policies !== false,
    }),
  })
}

export async function exportPack(body: PackExportRequest): Promise<PackManifestObject> {
  return packApi<PackManifestObject>("/api/packs/export", {
    method: "POST",
    body: JSON.stringify({
      pack_id: body.pack_id,
      include_user_modifications: Boolean(body.include_user_modifications),
      name: body.name || undefined,
      version: body.version || undefined,
      description: body.description || undefined,
    }),
  })
}

export async function rollbackPack(packId: string): Promise<PackRollbackResult> {
  return packApi<PackRollbackResult>(`/api/packs/${encodeURIComponent(packId)}/rollback`, {
    method: "POST",
  })
}

export async function uninstallPack(
  packId: string,
  keepUserModified = true,
): Promise<PackUninstallResult> {
  const query = `?keep_user_modified=${keepUserModified ? "true" : "false"}`
  return packApi<PackUninstallResult>(`/api/packs/${encodeURIComponent(packId)}${query}`, {
    method: "DELETE",
  })
}

export async function markPackResourceUserModified(
  resourceId: string,
  data?: Record<string, unknown> | null,
): Promise<PackResourceRecord> {
  return packApi<PackResourceRecord>(
    `/api/packs/resources/${encodeURIComponent(resourceId)}/user-modified`,
    {
      method: "POST",
      body: JSON.stringify({ data: data ?? null }),
    },
  )
}

/** Existing localhost portal callback for Amazon Ads OAuth. Not a secret. */
export const AMAZON_ADS_PORTAL_CALLBACK = "http://localhost:4780/api/amazon-ads/oauth/callback"

export const AMAZON_ADS_WRITE_AUTHORITY = {
  SUGGEST_ONLY: "SUGGEST_ONLY",
  EXECUTE_WITHIN_POLICY: "EXECUTE_WITHIN_POLICY",
} as const

export type AmazonAdsWriteAuthority =
  (typeof AMAZON_ADS_WRITE_AUTHORITY)[keyof typeof AMAZON_ADS_WRITE_AUTHORITY]

export const AMAZON_ADS_WINDOWS = [7, 14, 30] as const
export type AmazonAdsWindowDays = (typeof AMAZON_ADS_WINDOWS)[number]
export type AmazonAdsWindowKey = `${AmazonAdsWindowDays}d`

export type AmazonAdsWindowMetrics = {
  spend: number
  sales: number
  orders: number
  clicks: number
  impressions: number
  roas: number | null
  acos: number | null
  ctr: number | null
  cpc: number | null
  conversion_rate: number | null
}

export type AmazonAdsConnection = {
  id: string
  label?: string
  profile_ids?: string[]
  status?: string
  redirect_uri?: string
  token_expires_at?: string | null
  created_at?: string
  updated_at?: string
  revoked_at?: string | null
}

export type AmazonAdsBreakEven = {
  royalty_rate?: number
  margin_rate?: number
  other_costs_pct?: number
}

export type AmazonAdsHealth = {
  profile_id: string
  has_data: boolean
  updated_at?: string | null
  write_authority?: string
  break_even_roas?: AmazonAdsBreakEven | number | null
  connections?: number
}

export type AmazonAdsMetrics = {
  profile_id: string
  windows: Partial<Record<AmazonAdsWindowKey, AmazonAdsWindowMetrics>>
}

export type AmazonAdsEntityRow = AmazonAdsWindowMetrics & {
  entity_id?: string
  text?: string
  campaign_id?: string
}

export type AmazonAdsWinnersWaste = {
  winners: AmazonAdsEntityRow[]
  waste: AmazonAdsEntityRow[]
}

export type AmazonAdsRecommendation = {
  id: string
  provider?: string
  profile_id: string
  entity_type: string
  entity_id: string
  campaign_id?: string
  evidence_window_days?: number
  metrics?: Record<string, unknown>
  rationale: string
  proposed_action: string
  proposed_change?: Record<string, unknown>
  estimated_impact?: string
  confidence?: number
  originating_agent?: string
  status: string
  created_at?: string
}

export type AmazonAdsPolicy = {
  write_authority?: string
  max_bid_change_pct?: number
  max_budget_change_pct?: number
  absolute_daily_spend_ceiling?: number
  protected_entities?: string[]
  min_evidence_days?: number
  break_even?: AmazonAdsBreakEven
  acos_threshold?: number
  roas_threshold?: number
  high_spend_no_sale_threshold?: number
  low_conversion_click_threshold?: number
  cpc_change_threshold_pct?: number
}

export type AmazonAdsPolicyUpdate = {
  write_authority?: string
  max_bid_change_pct?: number
  max_budget_change_pct?: number
  absolute_daily_spend_ceiling?: number
  protected_entities?: string[]
  min_evidence_days?: number
  break_even?: AmazonAdsBreakEven
  acos_threshold?: number
  roas_threshold?: number
  high_spend_no_sale_threshold?: number
  low_conversion_click_threshold?: number
  cpc_change_threshold_pct?: number
}

export type AmazonAdsOAuthStart = {
  connection_id: string
  authorization_url: string
  state: string
}

export type AmazonAdsIngestResult = {
  ingested?: boolean
  profile_id?: string
  campaigns?: number
  keywords?: number
  recommendations?: number
  start_date?: string
  end_date?: string
}

export type AmazonAdsExecuteResult = {
  executed: boolean
  reason?: string
  recommendation_id?: string
  audit_id?: string
  api_result?: Record<string, unknown>
  evaluation?: unknown
}

export type AmazonAdsAuditEntry = {
  id?: string
  recommendation_id?: string
  entity_type?: string
  entity_id?: string
  action?: string
  actor?: string
  approval_source?: string
  timestamp?: string
  api_result?: Record<string, unknown>
}

export async function listAmazonAdsConnections(): Promise<{ connections: AmazonAdsConnection[] }> {
  return api<{ connections: AmazonAdsConnection[] }>("/api/amazon-ads/connections")
}

export async function getAmazonAdsHealth(profileId: string): Promise<AmazonAdsHealth> {
  return api<AmazonAdsHealth>(`/api/amazon-ads/health/${encodeURIComponent(profileId)}`)
}

export async function getAmazonAdsMetrics(profileId: string, endDate: string): Promise<AmazonAdsMetrics> {
  const query = `?end_date=${encodeURIComponent(endDate)}`
  return api<AmazonAdsMetrics>(`/api/amazon-ads/metrics/${encodeURIComponent(profileId)}${query}`)
}

export async function getAmazonAdsWinnersWaste(
  profileId: string,
  endDate: string,
  days: AmazonAdsWindowDays = 30,
): Promise<AmazonAdsWinnersWaste> {
  const query = `?end_date=${encodeURIComponent(endDate)}&days=${encodeURIComponent(String(days))}`
  return api<AmazonAdsWinnersWaste>(
    `/api/amazon-ads/winners-waste/${encodeURIComponent(profileId)}${query}`,
  )
}

export async function listAmazonAdsRecommendations(
  profileId?: string,
): Promise<{ recommendations: AmazonAdsRecommendation[] }> {
  const query = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ""
  return api<{ recommendations: AmazonAdsRecommendation[] }>(`/api/amazon-ads/recommendations${query}`)
}

export async function listAmazonAdsPendingApprovals(): Promise<{ pending: AmazonAdsRecommendation[] }> {
  return api<{ pending: AmazonAdsRecommendation[] }>("/api/amazon-ads/pending-approvals")
}

export async function approveAmazonAdsRecommendation(
  recId: string,
  actor = "portal-user",
): Promise<AmazonAdsRecommendation> {
  return api<AmazonAdsRecommendation>(
    `/api/amazon-ads/recommendations/${encodeURIComponent(recId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ actor }),
    },
  )
}

export async function executeAmazonAdsRecommendation(
  recId: string,
  body?: { actor?: string; approved?: boolean; approval_source?: string },
): Promise<AmazonAdsExecuteResult> {
  return api<AmazonAdsExecuteResult>(
    `/api/amazon-ads/recommendations/${encodeURIComponent(recId)}/execute`,
    {
      method: "POST",
      body: JSON.stringify({
        actor: body?.actor ?? "portal-user",
        approved: Boolean(body?.approved),
        approval_source: body?.approval_source ?? "manual",
      }),
    },
  )
}

export async function getAmazonAdsPolicy(): Promise<AmazonAdsPolicy> {
  return api<AmazonAdsPolicy>("/api/amazon-ads/policy")
}

export async function updateAmazonAdsPolicy(body: AmazonAdsPolicyUpdate): Promise<AmazonAdsPolicy> {
  return api<AmazonAdsPolicy>("/api/amazon-ads/policy", {
    method: "PUT",
    body: JSON.stringify(body),
  })
}

export async function listAmazonAdsAudit(
  recommendationId?: string,
): Promise<{ entries: AmazonAdsAuditEntry[] }> {
  const query = recommendationId
    ? `?recommendation_id=${encodeURIComponent(recommendationId)}`
    : ""
  return api<{ entries: AmazonAdsAuditEntry[] }>(`/api/amazon-ads/audit${query}`)
}

export async function ingestAmazonAds(body: {
  profile_id: string
  start_date: string
  end_date: string
}): Promise<AmazonAdsIngestResult> {
  return api<AmazonAdsIngestResult>("/api/amazon-ads/ingest", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function startAmazonAdsOAuth(body: {
  label: string
  profile_ids?: string[]
  redirect_uri?: string
}): Promise<AmazonAdsOAuthStart> {
  return api<AmazonAdsOAuthStart>("/api/amazon-ads/oauth/start", {
    method: "POST",
    body: JSON.stringify({
      label: body.label,
      profile_ids: body.profile_ids ?? [],
      redirect_uri: body.redirect_uri || AMAZON_ADS_PORTAL_CALLBACK,
    }),
  })
}

export const WORKER_ENVIRONMENT_STATUSES = ["created", "running", "suspended"] as const
export type WorkerEnvironmentLifecycle = (typeof WORKER_ENVIRONMENT_STATUSES)[number]

export type WorkerEnvironmentQuotas = {
  disk_mb?: number
  cpu_threads?: number
  ram_gb?: number
  gpu_percent?: number
  max_background_processes?: number
  [key: string]: number | undefined
}

export type WorkerEnvironmentStatus = {
  id: string
  name: string
  worker_kind: string
  agent_profile: string
  status: string
  created_at: string
  last_active_at: string
  suspended_at?: string | null
  quotas: WorkerEnvironmentQuotas | Record<string, unknown>
  metadata: Record<string, unknown>
  disk_usage_bytes: number
  disk_usage_mb: number
  quota_violations: string[]
}

export type WorkerEnvironmentCredential = {
  id: string
  environment_id: string
  capability: string
  label: string
  created_at: string
  revoked_at?: string | null
}

export type WorkerEnvironmentInspect = WorkerEnvironmentStatus & {
  workspace_path: string
  workspace_files: string[]
  caches_path: string
  browser_profile_path: string
  logs_path: string
  log_files: string[]
  processes: unknown[]
  task_state: Record<string, unknown>
  credentials: WorkerEnvironmentCredential[]
}

export type WorkerEnvironmentCreateIn = {
  name: string
  worker_kind?: string
  agent_profile?: string
  quotas?: WorkerEnvironmentQuotas
  metadata?: Record<string, unknown>
}

export type WorkerEnvironmentCredentialIn = {
  capability: string
  label: string
  secret: string
  credential_id?: string
}

export type WorkerEnvironmentAuditEvent = {
  timestamp: string
  event: string
  environment_id?: string | null
  credential_id?: string | null
  details?: Record<string, unknown>
}

export type WorkerEnvironmentDeleteResult = {
  deleted: boolean
  id: string
  name: string
}

export type WorkerEnvironmentsListResponse = {
  environments: WorkerEnvironmentStatus[]
}

export async function listWorkerEnvironments(): Promise<WorkerEnvironmentsListResponse> {
  return api<WorkerEnvironmentsListResponse>("/api/worker-environments")
}

export async function createWorkerEnvironment(
  body: WorkerEnvironmentCreateIn,
): Promise<WorkerEnvironmentStatus> {
  return api<WorkerEnvironmentStatus>("/api/worker-environments", {
    method: "POST",
    body: JSON.stringify({
      name: body.name,
      worker_kind: body.worker_kind || "general",
      agent_profile: body.agent_profile || "default",
      quotas: body.quotas || {},
      metadata: body.metadata || {},
    }),
  })
}

export async function listWorkerEnvironmentAudit(options?: {
  environmentId?: string
  limit?: number
}): Promise<{ events: WorkerEnvironmentAuditEvent[] }> {
  const params = new URLSearchParams()
  if (options?.environmentId) params.set("environment_id", options.environmentId)
  if (options?.limit != null) params.set("limit", String(options.limit))
  const query = params.toString()
  return api<{ events: WorkerEnvironmentAuditEvent[] }>(
    `/api/worker-environments/audit${query ? `?${query}` : ""}`,
  )
}

export async function inspectWorkerEnvironment(
  environmentId: string,
): Promise<WorkerEnvironmentInspect> {
  return api<WorkerEnvironmentInspect>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}`,
  )
}

export async function getWorkerEnvironmentStatus(
  environmentId: string,
): Promise<WorkerEnvironmentStatus> {
  return api<WorkerEnvironmentStatus>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}/status`,
  )
}

export async function startWorkerEnvironment(
  environmentId: string,
): Promise<WorkerEnvironmentStatus> {
  return api<WorkerEnvironmentStatus>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}/start`,
    { method: "POST" },
  )
}

export async function suspendWorkerEnvironment(
  environmentId: string,
): Promise<WorkerEnvironmentStatus> {
  return api<WorkerEnvironmentStatus>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}/suspend`,
    { method: "POST" },
  )
}

export async function resumeWorkerEnvironment(
  environmentId: string,
): Promise<WorkerEnvironmentStatus> {
  return api<WorkerEnvironmentStatus>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}/resume`,
    { method: "POST" },
  )
}

export async function resetWorkerEnvironment(
  environmentId: string,
): Promise<WorkerEnvironmentStatus> {
  return api<WorkerEnvironmentStatus>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}/reset`,
    { method: "POST" },
  )
}

export async function deleteWorkerEnvironment(
  environmentId: string,
): Promise<WorkerEnvironmentDeleteResult> {
  return api<WorkerEnvironmentDeleteResult>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}`,
    { method: "DELETE" },
  )
}

export async function storeWorkerEnvironmentCredential(
  environmentId: string,
  body: WorkerEnvironmentCredentialIn,
): Promise<WorkerEnvironmentCredential> {
  const payload: WorkerEnvironmentCredentialIn = {
    capability: body.capability,
    label: body.label,
    secret: body.secret,
  }
  if (body.credential_id) payload.credential_id = body.credential_id
  return api<WorkerEnvironmentCredential>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}/credentials`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  )
}

export async function revokeWorkerEnvironmentCredential(
  environmentId: string,
  credentialId: string,
): Promise<WorkerEnvironmentCredential> {
  return api<WorkerEnvironmentCredential>(
    `/api/worker-environments/${encodeURIComponent(environmentId)}/credentials/${encodeURIComponent(credentialId)}`,
    { method: "DELETE" },
  )
}

export const DELEGATION_STATUSES = ["pending", "running", "completed", "failed", "expired"] as const
export type DelegatedWorkerStatus = (typeof DELEGATION_STATUSES)[number]

export const DELEGATION_AUTONOMY = ["interactive", "trusted", "autonomous"] as const
export type DelegationAutonomy = (typeof DELEGATION_AUTONOMY)[number]

export const DELEGATION_PRIVACY = ["public", "internal", "confidential", "restricted"] as const
export type DelegationPrivacy = (typeof DELEGATION_PRIVACY)[number]

export const DELEGATION_AUTONOMY_RANK: Record<string, number> = {
  interactive: 0,
  trusted: 1,
  autonomous: 2,
}

export const DELEGATION_PRIVACY_RANK: Record<string, number> = {
  public: 0,
  internal: 1,
  confidential: 2,
  restricted: 3,
}

export const TASK_PARENT_PRIVACY = "internal"
export const PLATFORM_AUTONOMY_CAP = "autonomous"

export type DelegatedWorker = {
  id: string
  parent_task_id: string
  parent_worker_id: string | null
  depth: number
  task: string
  context: Record<string, unknown>
  tools: string[]
  budget: Record<string, unknown>
  result_schema: Record<string, unknown>
  autonomy: string
  privacy_class: string
  status: string
  result: Record<string, unknown> | null
  error: string | null
  created_at: string | null
  updated_at: string | null
  started_at: string | null
  finished_at: string | null
  deadline_at: string | null
  expires_at: string | null
}

export type DelegationEvent = {
  id: string | number
  parent_task_id: string
  worker_id: string
  kind: string
  title: string
  detail: string
  created_at: string | null
}

export type SpawnDelegatedChild = {
  task: string
  parent_worker_id?: string | null
  context?: Record<string, unknown>
  tools?: string[]
  budget?: Record<string, unknown>
  deadline_at?: string | null
  result_schema?: Record<string, unknown>
  autonomy?: string | null
  privacy_class?: string | null
  ttl_seconds?: number | null
}

export type DelegationAuthority = {
  tools: string[]
  autonomy: string
  privacy_class: string
  context: Record<string, unknown>
  budget: Record<string, number>
}

const DELEGATION_ERROR_COPY: Record<string, string> = {
  max_depth_exceeded:
    "This helper would sit too far below the parent. Jarvis limits how deep a chain of helpers can go.",
  max_fan_out_exceeded:
    "This parent already has as many active helpers as allowed. Wait for one to finish before adding another.",
  tool_not_allowed: "That tool is not on the parent, so it cannot be given to a helper.",
  context_not_allowed: "Helpers can only see details the parent already has.",
  parent_not_found: "That parent task or helper was not found.",
  parent_not_active: "Helpers can only be added under a helper that is still waiting or working.",
  invalid_task: "Describe what the helper should do.",
  worker_not_found: "That helper was not found.",
  worker_not_active: "That helper is no longer waiting or working.",
}

export class DelegationApiError extends Error {
  status: number
  code: string
  constructor(message: string, status: number, code = "") {
    super(message)
    this.name = "DelegationApiError"
    this.status = status
    this.code = code
  }
}

export function formatDelegationError(err: unknown): string {
  if (err instanceof DelegationApiError) {
    if (err.code && DELEGATION_ERROR_COPY[err.code]) return DELEGATION_ERROR_COPY[err.code]
    return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return "Could not update helpers."
}

function parentToolsForTask(task: Task): string[] {
  if (task.allowed_tools?.length) return task.allowed_tools
  if (task.exposed_tools?.length) return task.exposed_tools
  return []
}

export function authorityFromTask(task: Task): DelegationAuthority {
  return {
    tools: parentToolsForTask(task),
    autonomy: (task.autonomy || "trusted").toLowerCase(),
    privacy_class: TASK_PARENT_PRIVACY,
    context: {
      task_prompt: task.prompt || "",
      task_class: task.task_class || "",
    },
    budget: {},
  }
}

export function authorityFromWorker(worker: DelegatedWorker): DelegationAuthority {
  const budget: Record<string, number> = {}
  for (const [key, value] of Object.entries(worker.budget || {})) {
    if (typeof value === "number" && Number.isFinite(value)) budget[key] = value
  }
  return {
    tools: (worker.tools || []).map((item) => String(item)),
    autonomy: (worker.autonomy || "interactive").toLowerCase(),
    privacy_class: (worker.privacy_class || TASK_PARENT_PRIVACY).toLowerCase(),
    context: worker.context && typeof worker.context === "object" ? worker.context : {},
    budget,
  }
}

export function allowedDelegationAutonomy(parentAutonomy: string): DelegationAutonomy[] {
  const max = Math.min(
    DELEGATION_AUTONOMY_RANK[parentAutonomy.toLowerCase()] ?? 0,
    DELEGATION_AUTONOMY_RANK[PLATFORM_AUTONOMY_CAP] ?? 2,
  )
  return DELEGATION_AUTONOMY.filter((item) => (DELEGATION_AUTONOMY_RANK[item] ?? 0) <= max)
}

export function allowedDelegationPrivacy(parentPrivacy: string): DelegationPrivacy[] {
  const min = DELEGATION_PRIVACY_RANK[parentPrivacy.toLowerCase()] ?? DELEGATION_PRIVACY_RANK[TASK_PARENT_PRIVACY]
  return DELEGATION_PRIVACY.filter((item) => (DELEGATION_PRIVACY_RANK[item] ?? 0) >= min)
}

export function subsetDelegationTools(requested: string[], parentTools: string[]): string[] {
  const allowed = new Set(parentTools.map((item) => item.trim().toLowerCase()).filter(Boolean))
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of requested) {
    const key = String(item || "").trim().toLowerCase()
    if (!key || !allowed.has(key) || seen.has(key)) continue
    seen.add(key)
    out.push(key)
  }
  return out
}

export function clampDelegationSpawn(
  body: SpawnDelegatedChild,
  parent: DelegationAuthority,
): SpawnDelegatedChild {
  const allowedAuto = allowedDelegationAutonomy(parent.autonomy)
  const requestedAuto = (body.autonomy || parent.autonomy).toLowerCase()
  const autonomy = allowedAuto.includes(requestedAuto as DelegationAutonomy)
    ? requestedAuto
    : parent.autonomy

  const allowedPriv = allowedDelegationPrivacy(parent.privacy_class)
  const requestedPriv = (body.privacy_class || parent.privacy_class).toLowerCase()
  const privacy_class = allowedPriv.includes(requestedPriv as DelegationPrivacy)
    ? requestedPriv
    : parent.privacy_class

  const context: Record<string, unknown> = {}
  for (const key of Object.keys(body.context || {})) {
    if (Object.prototype.hasOwnProperty.call(parent.context, key)) {
      context[key] = parent.context[key]
    }
  }

  const budget: Record<string, unknown> = {}
  const parentKeys = Object.keys(parent.budget)
  for (const [key, value] of Object.entries(body.budget || {})) {
    if (typeof value !== "number" || !Number.isFinite(value)) continue
    if (parentKeys.length) {
      if (!(key in parent.budget)) continue
      budget[key] = Math.min(value, parent.budget[key])
    } else {
      budget[key] = value
    }
  }

  return {
    ...body,
    tools: subsetDelegationTools(body.tools || [], parent.tools),
    autonomy,
    privacy_class,
    context,
    budget,
  }
}

async function delegationApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders({
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  })
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const text = await response.text()
    let message = text || response.statusText
    let code = ""
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      if (parsed.detail && typeof parsed.detail === "object" && !Array.isArray(parsed.detail)) {
        const record = parsed.detail as { code?: unknown }
        if (typeof record.code === "string") code = record.code
      }
      message = formatApiDetail(parsed.detail, message)
    } catch {
      // keep text
    }
    if (code && DELEGATION_ERROR_COPY[code]) message = DELEGATION_ERROR_COPY[code]
    throw new DelegationApiError(message || response.statusText, response.status, code)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function listDelegationChildren(
  parentTaskId: string,
  parentWorkerId?: string | null,
): Promise<DelegatedWorker[]> {
  const params = new URLSearchParams()
  if (parentWorkerId) params.set("parent_worker_id", parentWorkerId)
  const query = params.toString()
  return delegationApi<DelegatedWorker[]>(
    `/api/delegation/parents/${encodeURIComponent(parentTaskId)}/children${query ? `?${query}` : ""}`,
  )
}

export async function listDelegationGraph(parentTaskId: string): Promise<DelegatedWorker[]> {
  const out: DelegatedWorker[] = []
  const seen = new Set<string>()

  async function walk(parentWorkerId?: string, depth = 0): Promise<void> {
    if (depth > 8) return
    const kids = await listDelegationChildren(parentTaskId, parentWorkerId)
    const next: DelegatedWorker[] = []
    for (const kid of kids) {
      if (seen.has(kid.id)) continue
      seen.add(kid.id)
      out.push(kid)
      next.push(kid)
    }
    await Promise.all(next.map((kid) => walk(kid.id, depth + 1)))
  }

  await walk()
  return out
}

export async function listDelegationEvents(parentTaskId: string): Promise<DelegationEvent[]> {
  return delegationApi<DelegationEvent[]>(
    `/api/delegation/parents/${encodeURIComponent(parentTaskId)}/events`,
  )
}

export async function getDelegatedWorker(workerId: string): Promise<DelegatedWorker> {
  return delegationApi<DelegatedWorker>(`/api/delegation/workers/${encodeURIComponent(workerId)}`)
}

export async function spawnDelegatedChild(
  parentTaskId: string,
  body: SpawnDelegatedChild,
  parentAuthority?: DelegationAuthority,
): Promise<DelegatedWorker> {
  const payload = parentAuthority ? clampDelegationSpawn(body, parentAuthority) : { ...body }
  const request: Record<string, unknown> = {
    task: payload.task,
    context: payload.context || {},
    tools: payload.tools || [],
    budget: payload.budget || {},
    result_schema: payload.result_schema || {},
  }
  if (payload.parent_worker_id) request.parent_worker_id = payload.parent_worker_id
  if (payload.deadline_at) request.deadline_at = payload.deadline_at
  if (payload.autonomy) request.autonomy = payload.autonomy
  if (payload.privacy_class) request.privacy_class = payload.privacy_class
  if (payload.ttl_seconds != null) request.ttl_seconds = payload.ttl_seconds
  return delegationApi<DelegatedWorker>(
    `/api/delegation/parents/${encodeURIComponent(parentTaskId)}/children`,
    { method: "POST", body: JSON.stringify(request) },
  )
}

export async function startDelegatedWorker(workerId: string): Promise<DelegatedWorker> {
  return delegationApi<DelegatedWorker>(
    `/api/delegation/workers/${encodeURIComponent(workerId)}/start`,
    { method: "POST" },
  )
}

export async function completeDelegatedWorker(
  workerId: string,
  result: Record<string, unknown> = {},
): Promise<DelegatedWorker> {
  return delegationApi<DelegatedWorker>(
    `/api/delegation/workers/${encodeURIComponent(workerId)}/complete`,
    { method: "POST", body: JSON.stringify({ result }) },
  )
}

export async function failDelegatedWorker(workerId: string, error: string): Promise<DelegatedWorker> {
  return delegationApi<DelegatedWorker>(
    `/api/delegation/workers/${encodeURIComponent(workerId)}/fail`,
    { method: "POST", body: JSON.stringify({ error }) },
  )
}

export type LicenseValidationStatus =
  | "unlicensed"
  | "tamper_detected"
  | "invalid_signature"
  | "cluster_mismatch"
  | "not_yet_valid"
  | "expired"
  | "grace"
  | "active"
  | "valid"

export type LicenseValidation = {
  valid?: boolean
  status?: string
  message?: string
  cluster_id?: string
  lease_id?: string
  tier?: string
  features?: string[]
  pack_entitlements?: string[]
  issued_at?: string
  expires_at?: string
  grace_seconds?: number
  in_grace?: boolean
  last_validated_at?: string
}

export type LicenseStatus = {
  cluster_id: string
  validation: LicenseValidation
  lease_present: boolean
  last_status: string | null
  last_message: string | null
  last_validated_at: string | null
}

export type LicenseCluster = {
  cluster_id: string
}

export type LicenseEntitlements = {
  tier: string | null
  features: string[]
  pack_entitlements: string[]
  cluster_wide?: boolean
  cluster_id?: string
}

export type LicenseEntitlementsResponse = {
  validation: LicenseValidation
  entitlements: LicenseEntitlements
}

export type SignedLeaseObject = {
  payload?: Record<string, unknown>
  signature?: string
  signer_key_id?: string
  [key: string]: unknown
}

/** Public inference credential fields only. Never include secret. */
export type InferenceCredentialPublic = {
  id: string
  provider: string
  label: string
  endpoint?: string | null
}

export type InferenceCredentialIn = {
  provider: string
  label: string
  secret: string
  endpoint?: string | null
  credential_id?: string
  metadata?: Record<string, unknown>
}

function asOptionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item)).filter(Boolean)
}

function publicInferenceCredential(raw: unknown): InferenceCredentialPublic | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  const id = asOptionalString(row.id) || asOptionalString(row.credential_id)
  if (!id) return null
  return {
    id,
    provider: asOptionalString(row.provider) || "",
    label: asOptionalString(row.label) || "",
    endpoint: asOptionalString(row.endpoint) || null,
  }
}

function publicInferenceCredentials(raw: unknown): InferenceCredentialPublic[] {
  const list = Array.isArray(raw) ? raw : []
  const out: InferenceCredentialPublic[] = []
  for (const item of list) {
    const pub = publicInferenceCredential(item)
    if (pub) out.push(pub)
  }
  return out
}

export async function getLicenseStatus(): Promise<LicenseStatus> {
  return api<LicenseStatus>("/api/license/status")
}

export async function getLicenseCluster(): Promise<LicenseCluster> {
  return api<LicenseCluster>("/api/license/cluster")
}

export async function validateLicenseOffline(): Promise<LicenseValidation> {
  return api<LicenseValidation>("/api/license/validate", { method: "POST" })
}

export async function refreshLicenseLease(lease: SignedLeaseObject): Promise<LicenseValidation> {
  return api<LicenseValidation>("/api/license/refresh", {
    method: "POST",
    body: JSON.stringify({ lease }),
  })
}

export async function getLicenseEntitlements(): Promise<LicenseEntitlementsResponse> {
  const data = await api<LicenseEntitlementsResponse>("/api/license/entitlements")
  const entitlements = data.entitlements || {
    tier: null,
    features: [],
    pack_entitlements: [],
  }
  return {
    validation: data.validation || {},
    entitlements: {
      tier: entitlements.tier ?? null,
      features: asStringList(entitlements.features),
      pack_entitlements: asStringList(entitlements.pack_entitlements),
      cluster_wide: entitlements.cluster_wide !== false,
      cluster_id: asOptionalString(entitlements.cluster_id),
    },
  }
}

export async function listInferenceCredentials(): Promise<{ credentials: InferenceCredentialPublic[] }> {
  const data = await api<{ credentials?: unknown }>("/api/license/inference-credentials")
  return { credentials: publicInferenceCredentials(data.credentials) }
}

export async function upsertInferenceCredential(
  body: InferenceCredentialIn,
): Promise<{ credential: InferenceCredentialPublic }> {
  const payload: Record<string, unknown> = {
    provider: body.provider,
    label: body.label,
    secret: body.secret,
  }
  if (body.endpoint) payload.endpoint = body.endpoint
  if (body.credential_id) payload.credential_id = body.credential_id
  if (body.metadata && Object.keys(body.metadata).length) payload.metadata = body.metadata
  const data = await api<{ credential?: unknown }>("/api/license/inference-credentials", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  const credential = publicInferenceCredential(data.credential)
  if (!credential) throw new Error("Saved, but Jarvis did not return a credential id.")
  return { credential }
}

export async function deleteInferenceCredential(
  credentialId: string,
): Promise<{ deleted: boolean; id: string }> {
  return api<{ deleted: boolean; id: string }>(
    `/api/license/inference-credentials/${encodeURIComponent(credentialId)}`,
    { method: "DELETE" },
  )
}

export const ADVISOR_STUB_PROVIDER = "stub"

export type AdvisorDisclosureField = {
  key: string
  label: string
  value: unknown
  bytes_estimate: number
  leaves_local: boolean
}

export type AdvisorPreviewRequest = {
  goal: string
  task_class?: string
  observations?: string[]
  failed_approaches?: string[]
  unresolved_problem?: string
  relevant_files?: string[]
  retained_facts?: string[]
  consecutive_failures?: number
  confidence?: number
  local_attempts?: number
  already_escalated?: number
  user_requested?: boolean
  max_cost_usd?: number
  advisor_cost_usd?: number
}

export type AdvisorDisclosurePackage = {
  id: string
  version: string
  created_at: string
  goal: string
  task_class: string
  fields: AdvisorDisclosureField[]
  local_only_retained: string[]
  outbound: Record<string, unknown>
  token_estimate: number
  cost_estimate_usd: number | null
  outbound_preview: Record<string, unknown>
}

export type AdvisorEscalateRequest = {
  package_id: string
  provider?: string
  consecutive_failures?: number
  confidence?: number
  local_attempts?: number
  already_escalated?: number
  user_requested?: boolean
  max_cost_usd?: number
  advisor_cost_usd?: number
}

export type AdvisorResponse = {
  analysis: string
  recommendations: string[]
  structured_plan: Record<string, unknown> | null
  advisor_name: string
  used: boolean
  reason: string
  execution_authority: string
  tool_calls: unknown[] | null
}

export class AdvisorApiError extends Error {
  status: number
  code: string
  constructor(message: string, status: number, code = "") {
    super(message)
    this.name = "AdvisorApiError"
    this.status = status
    this.code = code
  }
}

export function formatAdvisorError(err: unknown): string {
  if (err instanceof AdvisorApiError) {
    if (err.code === "authority_violation" || err.status === 403) {
      return "This advisor is blocked. Advisors cannot run tools, open files, spend money, or change anything on this PC. Only the local orchestrator can act."
    }
    if (err.code === "package_not_found" || err.status === 404) {
      return "That preview is no longer available. Show a new preview of what would leave this PC before asking the advisor."
    }
    if (err.status === 400) {
      return err.message || "The advisor request could not be completed. Check the details and try again."
    }
    return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return "Something went wrong talking to the advisor."
}

async function advisorApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders({
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  })
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const text = await response.text()
    let message = text || response.statusText
    let code = ""
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      const detail = parsed.detail
      if (detail && typeof detail === "object" && !Array.isArray(detail)) {
        const record = detail as { code?: unknown; message?: unknown }
        if (typeof record.code === "string") code = record.code
      }
      message = formatApiDetail(parsed.detail, message)
    } catch {
      // keep text
    }
    if (!code) {
      if (response.status === 403) code = "authority_violation"
      else if (response.status === 404) code = "package_not_found"
    }
    throw new AdvisorApiError(message || response.statusText, response.status, code)
  }
  return response.json() as Promise<T>
}

export async function previewAdvisor(body: AdvisorPreviewRequest): Promise<AdvisorDisclosurePackage> {
  return advisorApi<AdvisorDisclosurePackage>("/api/advisor/preview", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function getAdvisorPackage(packageId: string): Promise<AdvisorDisclosurePackage> {
  return advisorApi<AdvisorDisclosurePackage>(
    `/api/advisor/packages/${encodeURIComponent(packageId)}`,
  )
}

export async function escalateAdvisor(body: AdvisorEscalateRequest): Promise<AdvisorResponse> {
  return advisorApi<AdvisorResponse>("/api/advisor/escalate", {
    method: "POST",
    body: JSON.stringify({
      ...body,
      provider: body.provider || ADVISOR_STUB_PROVIDER,
    }),
  })
}

export const CONTEXT_ENTRY_CATEGORIES = [
  "identity",
  "projects",
  "procedures",
  "lessons",
  "priorities",
  "skills",
] as const
export type ContextEntryCategory = (typeof CONTEXT_ENTRY_CATEGORIES)[number]

export type ContextEntryProvenance = {
  source_type: string
  source_id?: string | null
  trajectory_id?: string | null
  mutation_id?: string | null
  note?: string | null
  created_at: string
}

export type ContextEntry = {
  id: string
  category: string
  title: string
  content: string
  pinned: boolean
  active: boolean
  conflicts_with: string[]
  provenance: ContextEntryProvenance
  superseded_by?: string | null
  metadata?: Record<string, unknown>
}

export type ContextRepoVersion = {
  schema_version: string
  agent_id: string
  version: number
  created_at: string
  parent_version?: number | null
  entries: ContextEntry[]
}

export type ContextRepoVersionSummary = {
  version: number
  created_at: string
  parent_version?: number | null
  entry_count: number
}

export type ContextMutationRecord = {
  mutation_id: string
  agent_id: string
  version_before: number
  version_after: number
  action: string
  entry_id?: string | null
  source: ContextEntryProvenance
  before?: ContextEntry | null
  after?: ContextEntry | null
  reversible: boolean
  reverted_by?: string | null
  created_at: string
}

export type ContextVersionDiffChange = {
  before: ContextEntry
  after: ContextEntry
}

export type ContextVersionDiff = {
  agent_id: string
  from_version: number
  to_version: number
  added: ContextEntry[]
  removed: ContextEntry[]
  changed: ContextVersionDiffChange[]
  conflicts_flagged: string[]
}

export type ContextEntryPermission = {
  principal_type: string
  principal_id: string
  permission: string
  created_at?: string | null
}

export type ContextEntryInspect = ContextEntry & {
  permissions?: ContextEntryPermission[]
}

export type ContextEntryCreate = {
  category: string
  title: string
  content: string
  source_type?: string
  source_id?: string | null
  trajectory_id?: string | null
  note?: string | null
}

export type ContextEntryCreateResult = {
  entry: ContextEntry
  version: number
  mutation_id: string
}

export type ContextConsolidationNode = {
  node_id?: string
  hostname?: string
  score?: number
  status?: string
  class?: string
  utilization?: number
  reasons?: string[]
  preferred?: boolean
}

export type ContextSchedulePreference = {
  nodes: ContextConsolidationNode[]
  preferred: ContextConsolidationNode[]
}

export class ContextRepoApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = "ContextRepoApiError"
    this.status = status
  }
}

function plainContextMessage(message: string): string {
  const trimmed = message.trim()
  const lower = trimmed.toLowerCase()
  if (lower.includes("duplicate")) {
    return "This note already exists. Nothing was added."
  }
  if (lower.includes("already reverted")) {
    return "That change was already undone."
  }
  if (lower.includes("pinned entries cannot be deleted")) {
    return "Pinned notes cannot be removed. Unpin first, then try again."
  }
  if (lower.includes("not reversible") || lower.includes("cannot revert this mutation")) {
    return "This change cannot be undone."
  }
  if (lower.includes("one or both versions do not exist")) {
    return "One of those versions is missing. Pick two versions that are on file."
  }
  if (lower.includes("unsupported category")) {
    return "That kind of note is not supported."
  }
  if (lower.includes("entry not found")) {
    return "That note is no longer here."
  }
  if (lower.includes("version not found")) {
    return "That version is not on file."
  }
  if (lower.includes("mutation not found")) {
    return "That change is not on file."
  }
  return trimmed || "Something went wrong with saved notes."
}

export function formatContextRepoError(err: unknown): string {
  if (err instanceof ContextRepoApiError) {
    const plain = plainContextMessage(err.message)
    if (err.status === 409) {
      if (plain === err.message) {
        return `This note conflicts with one already saved. ${plain}`
      }
      return plain
    }
    return plain
  }
  if (err instanceof Error && err.message) return plainContextMessage(err.message)
  return "Something went wrong with saved notes."
}

async function contextRepoApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders({
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  })
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const text = await response.text()
    let message = text || response.statusText
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      message = formatApiDetail(parsed.detail, message)
    } catch {
      // keep text
    }
    throw new ContextRepoApiError(message || response.statusText, response.status)
  }
  return response.json() as Promise<T>
}

function contextRepoPath(agentId: string, suffix = ""): string {
  return `/api/context-repo/${encodeURIComponent(agentId)}${suffix}`
}

export async function getContextRepo(agentId: string): Promise<ContextRepoVersion> {
  return contextRepoApi<ContextRepoVersion>(contextRepoPath(agentId))
}

export async function listContextRepoVersions(agentId: string): Promise<ContextRepoVersionSummary[]> {
  return contextRepoApi<ContextRepoVersionSummary[]>(contextRepoPath(agentId, "/versions"))
}

export async function getContextRepoVersion(agentId: string, version: number): Promise<ContextRepoVersion> {
  return contextRepoApi<ContextRepoVersion>(contextRepoPath(agentId, `/versions/${encodeURIComponent(String(version))}`))
}

export async function getContextRepoDiff(
  agentId: string,
  fromVersion: number,
  toVersion: number,
): Promise<ContextVersionDiff> {
  const query = `?from_version=${encodeURIComponent(String(fromVersion))}&to_version=${encodeURIComponent(String(toVersion))}`
  return contextRepoApi<ContextVersionDiff>(contextRepoPath(agentId, `/diff${query}`))
}

export async function listContextRepoHistory(
  agentId: string,
  limit = 100,
): Promise<ContextMutationRecord[]> {
  const query = `?limit=${encodeURIComponent(String(limit))}`
  return contextRepoApi<ContextMutationRecord[]>(contextRepoPath(agentId, `/history${query}`))
}

export async function getContextRepoEntry(agentId: string, entryId: string): Promise<ContextEntryInspect> {
  return contextRepoApi<ContextEntryInspect>(
    contextRepoPath(agentId, `/entries/${encodeURIComponent(entryId)}`),
  )
}

export async function createContextRepoEntry(
  agentId: string,
  body: ContextEntryCreate,
): Promise<ContextEntryCreateResult> {
  return contextRepoApi<ContextEntryCreateResult>(contextRepoPath(agentId, "/entries"), {
    method: "POST",
    body: JSON.stringify({
      category: body.category,
      title: body.title,
      content: body.content,
      source_type: body.source_type || "manual",
      source_id: body.source_id || null,
      trajectory_id: body.trajectory_id || null,
      note: body.note || null,
    }),
  })
}

export async function pinContextRepoEntry(
  agentId: string,
  entryId: string,
  pinned: boolean,
): Promise<ContextEntry> {
  return contextRepoApi<ContextEntry>(
    contextRepoPath(agentId, `/entries/${encodeURIComponent(entryId)}/pin`),
    {
      method: "POST",
      body: JSON.stringify({ pinned }),
    },
  )
}

export async function deleteContextRepoEntry(agentId: string, entryId: string): Promise<ContextEntry> {
  return contextRepoApi<ContextEntry>(
    contextRepoPath(agentId, `/entries/${encodeURIComponent(entryId)}`),
    { method: "DELETE" },
  )
}

export async function revertContextRepoMutation(
  agentId: string,
  mutationId: string,
): Promise<ContextRepoVersion> {
  return contextRepoApi<ContextRepoVersion>(
    contextRepoPath(agentId, `/revert/${encodeURIComponent(mutationId)}`),
    { method: "POST" },
  )
}

export async function getContextRepoSchedulePreference(): Promise<ContextSchedulePreference> {
  return contextRepoApi<ContextSchedulePreference>("/api/context-repo/consolidate/schedule-preference")
}

export type TrajectoryOutcome = {
  status: string
  attempted?: boolean
  verified?: boolean
  summary?: string | null
}

export type TrajectoryProvenance = {
  harness: string
  harness_version?: string | null
  model?: string | null
  source_uri?: string | null
  source_format?: string | null
  imported_at: string
  import_id?: string | null
  trusted?: boolean
}

export type TrajectoryWorkspace = {
  repository?: string | null
  branch?: string | null
  workspace_path?: string | null
}

export type TrajectoryEvent = {
  sequence: number
  timestamp: string
  event_type: string
  content?: string | null
  tool_name?: string | null
  tool_args?: Record<string, unknown> | null
  tool_result?: string | null
  success?: boolean | null
  metadata?: Record<string, unknown>
}

export type TrajectoryVerification = {
  attempted?: boolean
  passed?: boolean
  details?: string | null
}

export type TrajectoryCandidateSkill = {
  name?: string | null
  tools?: string[]
  description?: string | null
  confidence?: number
}

export type TrajectorySummary = {
  trajectory_id: string
  schema_version?: string
  harness?: string | null
  model?: string | null
  goal?: string | null
  outcome_status?: string | null
  outcome_verified?: boolean
  trusted?: boolean
  imported_at?: string | null
  event_count?: number
}

export type TrajectoryInspect = {
  schema_version?: string
  trajectory_id: string
  goal?: string | null
  task_class?: string | null
  provenance: TrajectoryProvenance
  workspace?: TrajectoryWorkspace | null
  events: TrajectoryEvent[]
  outcome: TrajectoryOutcome
  verification?: TrajectoryVerification | null
  failures?: string[]
  recovery?: string | null
  candidate_skills?: TrajectoryCandidateSkill[]
  duration_seconds?: number | null
}

export type CursorTrajectoryImportIn = {
  transcript: string
  source_uri?: string
  model?: string
  repository?: string
  branch?: string
  workspace_path?: string
}

export type CursorTrajectoryImportResult = {
  trajectory_id: string
  harness: string
  event_count: number
  outcome: TrajectoryOutcome
  trusted: boolean
}

export type NativeTrajectoryEmitIn = {
  task_id: string
  model?: string
}

export type NativeTrajectoryEmitResult = {
  trajectory_id: string
  harness: string
  trusted: boolean
}

export type PendingTrajectoryItem = {
  trajectory_id: string
  harness: string
}

export class TrajectoryApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = "TrajectoryApiError"
    this.status = status
  }
}

export function formatTrajectoryError(err: unknown): string {
  if (err instanceof TrajectoryApiError) {
    if (err.status === 404) {
      const detail = err.message.toLowerCase()
      if (detail.includes("no native trajectory") || detail.includes("task")) {
        return "This task has no saved Jarvis run to record. Finish a task on this PC first, then try again."
      }
      return "That record was not found. It may have been removed."
    }
    if (err.status === 400) {
      const detail = err.message.toLowerCase()
      if (detail.includes("empty")) return "Paste a Cursor transcript first."
      if (detail.includes("invalid json") || detail.includes("json object")) {
        return "That Cursor transcript could not be read. Check it is a line-by-line JSON export and try again."
      }
      return err.message || "That transcript could not be imported."
    }
    return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return "Something went wrong with this record."
}

async function trajectoryApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders({
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  })
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const text = await response.text()
    let message = text || response.statusText
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      message = formatApiDetail(parsed.detail, message)
    } catch {
      // keep text
    }
    throw new TrajectoryApiError(message || response.statusText, response.status)
  }
  return response.json() as Promise<T>
}

export async function listTrajectories(limit = 50): Promise<TrajectorySummary[]> {
  const capped = Math.max(1, Math.min(limit, 500))
  return trajectoryApi<TrajectorySummary[]>(`/api/trajectories?limit=${encodeURIComponent(String(capped))}`)
}

export async function getTrajectory(trajectoryId: string): Promise<TrajectoryInspect> {
  return trajectoryApi<TrajectoryInspect>(`/api/trajectories/${encodeURIComponent(trajectoryId)}`)
}

export async function importCursorTrajectory(
  body: CursorTrajectoryImportIn,
): Promise<CursorTrajectoryImportResult> {
  return trajectoryApi<CursorTrajectoryImportResult>("/api/trajectories/import/cursor", {
    method: "POST",
    body: JSON.stringify({
      transcript: body.transcript,
      source_uri: body.source_uri || undefined,
      model: body.model || undefined,
      repository: body.repository || undefined,
      branch: body.branch || undefined,
      workspace_path: body.workspace_path || undefined,
    }),
  })
}

export async function emitNativeTrajectory(
  body: NativeTrajectoryEmitIn,
): Promise<NativeTrajectoryEmitResult> {
  return trajectoryApi<NativeTrajectoryEmitResult>("/api/trajectories/emit/native", {
    method: "POST",
    body: JSON.stringify({
      task_id: body.task_id,
      model: body.model || undefined,
    }),
  })
}

export async function listPendingTrajectories(): Promise<PendingTrajectoryItem[]> {
  return trajectoryApi<PendingTrajectoryItem[]>("/api/trajectories/queue/pending")
}

export const PORTABLE_AGENT_STATUSES = ["idle", "running", "suspended"] as const
export type PortableAgentStatus = (typeof PORTABLE_AGENT_STATUSES)[number]

export const PORTABLE_LEASE_STATUSES = ["active", "released"] as const
export type PortableLeaseStatus = (typeof PORTABLE_LEASE_STATUSES)[number]

export type PortableAgentState = {
  memory: Record<string, unknown>
  policy: Record<string, unknown>
  skill_refs: string[]
  goals: Record<string, unknown>[]
  task_state: Record<string, unknown>
  provenance: Record<string, unknown>[]
  required_tools: string[]
  required_capabilities: string[]
}

export type PortableAgent = {
  id: string
  name: string
  status: string
  state_version: number
  state: PortableAgentState
  created_at: string | null
  updated_at: string | null
  active_lease?: AgentRuntimeLease | null
  lease?: AgentRuntimeLease | null
  previous_lease?: AgentRuntimeLease | null
}

export type AgentRuntimeLease = {
  id: string
  agent_id: string
  runtime_profile_id: string
  node_id: string
  model: string
  endpoint: string
  status: string
  created_at: string | null
  released_at: string | null
}

export type PortabilityAuditEvent = {
  id: string
  agent_id: string
  event: string
  runtime_profile_id: string
  node_id: string
  model: string
  endpoint: string
  detail: string
  created_at: string | null
}

export type PortableAgentCreateIn = {
  name: string
  memory?: Record<string, unknown>
  skill_refs?: string[]
  goals?: Record<string, unknown>[]
  task_state?: Record<string, unknown>
  required_tools?: string[]
  required_capabilities?: string[]
}

/** Portable-state PATCH. Policy/autonomy is omitted so this portal cannot raise authority. */
export type PortableAgentStateUpdate = {
  memory?: Record<string, unknown>
  skill_refs?: string[]
  goals?: Record<string, unknown>[]
  task_state?: Record<string, unknown>
  provenance?: Record<string, unknown>[]
  required_tools?: string[]
  required_capabilities?: string[]
}

export type PortableLeaseRequest = {
  runtime_profile_id: string
  node_id?: string
}

export type PortableMigrateRequest = {
  target_runtime_profile_id: string
  node_id?: string
}

const PORTABILITY_ERROR_COPY: Record<string, string> = {
  missing_capabilities:
    "This runtime cannot run this agent. It is missing capabilities the agent needs. Jarvis did not silently pick a weaker setup. The Agent ID is unchanged.",
  missing_tools:
    "This runtime cannot run this agent. It does not have the tools the agent requires. Jarvis did not silently pick a weaker setup. The Agent ID is unchanged.",
  runtime_incompatible:
    "This runtime is not a match for this agent. Jarvis did not silently switch to a weaker setup. The Agent ID is unchanged.",
  lease_active:
    "This agent already has a runtime lease. Release it, or move the lease to a different runtime. The Agent ID is unchanged.",
  runtime_not_found: "That runtime was not found. Pick one from the list under Model.",
  agent_not_found: "That agent was not found.",
  lease_not_found: "That lease was not found.",
  lease_not_active: "That lease is no longer active.",
  invalid_status: "This agent cannot resume in its current state. Idle or suspended agents can resume.",
  invalid_state: "This agent’s portable state could not be read.",
  unsupported_state_version: "This agent’s saved state uses a version this portal cannot restore.",
}

export class PortabilityApiError extends Error {
  status: number
  code: string
  constructor(message: string, status: number, code = "") {
    super(message)
    this.name = "PortabilityApiError"
    this.status = status
    this.code = code
  }
}

export function formatPortabilityError(err: unknown): string {
  if (err instanceof PortabilityApiError) {
    if (err.code && PORTABILITY_ERROR_COPY[err.code]) return PORTABILITY_ERROR_COPY[err.code]
    if (err.status === 409) {
      return "This runtime cannot take the agent. Jarvis did not silently switch to a weaker setup. The Agent ID is unchanged."
    }
    if (err.status === 404) {
      return err.message || "That agent or lease was not found."
    }
    return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return "Could not update this agent’s runtime lease."
}

export function emptyPortableAgentState(): PortableAgentState {
  return {
    memory: {},
    policy: {},
    skill_refs: [],
    goals: [],
    task_state: {},
    provenance: [],
    required_tools: [],
    required_capabilities: [],
  }
}

function portabilityCodeFromDetail(detail: unknown): string {
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const record = detail as { code?: unknown }
    if (typeof record.code === "string") return record.code
  }
  return ""
}

async function portabilityApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders({
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  })
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const text = await response.text()
    let message = text || response.statusText
    let code = ""
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      code = portabilityCodeFromDetail(parsed.detail)
      message = formatApiDetail(parsed.detail, message)
    } catch {
      // keep text
    }
    if (code && PORTABILITY_ERROR_COPY[code]) message = PORTABILITY_ERROR_COPY[code]
    else if (response.status === 409 && !code) {
      message =
        "This runtime cannot take the agent. Jarvis did not silently switch to a weaker setup. The Agent ID is unchanged."
    }
    throw new PortabilityApiError(message || response.statusText, response.status, code)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function listPortableAgents(limit = 100): Promise<{ agents: PortableAgent[] }> {
  const capped = Math.max(1, Math.min(limit, 500))
  return portabilityApi<{ agents: PortableAgent[] }>(
    `/api/agent-portability?limit=${encodeURIComponent(String(capped))}`,
  )
}

export async function createPortableAgent(body: PortableAgentCreateIn): Promise<PortableAgent> {
  const payload: Record<string, unknown> = {
    name: body.name,
    memory: body.memory || {},
    skill_refs: body.skill_refs || [],
    goals: body.goals || [],
    task_state: body.task_state || {},
    required_tools: body.required_tools || [],
    required_capabilities: body.required_capabilities || [],
  }
  return portabilityApi<PortableAgent>("/api/agent-portability", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function getPortableAgent(agentId: string): Promise<PortableAgent> {
  return portabilityApi<PortableAgent>(`/api/agent-portability/${encodeURIComponent(agentId)}`)
}

export async function updatePortableAgentState(
  agentId: string,
  body: PortableAgentStateUpdate,
): Promise<PortableAgent> {
  const payload: Record<string, unknown> = {}
  if (body.memory !== undefined) payload.memory = body.memory
  if (body.skill_refs !== undefined) payload.skill_refs = body.skill_refs
  if (body.goals !== undefined) payload.goals = body.goals
  if (body.task_state !== undefined) payload.task_state = body.task_state
  if (body.provenance !== undefined) payload.provenance = body.provenance
  if (body.required_tools !== undefined) payload.required_tools = body.required_tools
  if (body.required_capabilities !== undefined) payload.required_capabilities = body.required_capabilities
  return portabilityApi<PortableAgent>(
    `/api/agent-portability/${encodeURIComponent(agentId)}/state`,
    { method: "PUT", body: JSON.stringify(payload) },
  )
}

export async function leasePortableAgent(
  agentId: string,
  body: PortableLeaseRequest,
): Promise<AgentRuntimeLease> {
  return portabilityApi<AgentRuntimeLease>(
    `/api/agent-portability/${encodeURIComponent(agentId)}/lease`,
    {
      method: "POST",
      body: JSON.stringify({
        runtime_profile_id: body.runtime_profile_id,
        node_id: body.node_id || "localhost",
      }),
    },
  )
}

export async function migratePortableAgent(
  agentId: string,
  body: PortableMigrateRequest,
): Promise<PortableAgent> {
  return portabilityApi<PortableAgent>(
    `/api/agent-portability/${encodeURIComponent(agentId)}/migrate`,
    {
      method: "POST",
      body: JSON.stringify({
        target_runtime_profile_id: body.target_runtime_profile_id,
        node_id: body.node_id || "localhost",
      }),
    },
  )
}

export async function suspendPortableAgent(agentId: string): Promise<PortableAgent> {
  return portabilityApi<PortableAgent>(
    `/api/agent-portability/${encodeURIComponent(agentId)}/suspend`,
    { method: "POST" },
  )
}

export async function resumePortableAgent(
  agentId: string,
  body: PortableLeaseRequest,
): Promise<PortableAgent> {
  return portabilityApi<PortableAgent>(
    `/api/agent-portability/${encodeURIComponent(agentId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify({
        runtime_profile_id: body.runtime_profile_id,
        node_id: body.node_id || "localhost",
      }),
    },
  )
}

export async function releasePortableAgentLease(leaseId: string): Promise<AgentRuntimeLease> {
  return portabilityApi<AgentRuntimeLease>(
    `/api/agent-portability/leases/${encodeURIComponent(leaseId)}`,
    { method: "DELETE" },
  )
}

export async function listPortableAgentAudit(options?: {
  agentId?: string
  limit?: number
}): Promise<{ events: PortabilityAuditEvent[] }> {
  const params = new URLSearchParams()
  if (options?.agentId) params.set("agent_id", options.agentId)
  if (options?.limit != null) params.set("limit", String(options.limit))
  const query = params.toString()
  return portabilityApi<{ events: PortabilityAuditEvent[] }>(
    `/api/agent-portability/audit${query ? `?${query}` : ""}`,
  )
}

export type CodingTaskDiff = {
  base?: string
  head?: string
  stat?: string
  files?: string
  [key: string]: unknown
}

export type CodingTaskRecord = {
  task_id: string
  base_sha: string
  branch: string
  worktree_id: string
  worktree_path: string
  status: string
  commits: string[]
  tests: Record<string, unknown>
  final_diff: CodingTaskDiff
  integration_status: string
  verifier_approved: boolean
  approved_by: string
  approved_at: string
  created_at: string
  completed_at: string
  cleaned_up: boolean
}

export type CodingDecisionInboxItem = {
  id: string
  kind: string
  title: string
  detail: string
  task_id: string
  related_task_id: string
  status: string
  created_at: string
  resolved_at: string
  resolution: string
}

export type CodingOverview = {
  workers?: { id?: string; name?: string; available?: boolean; status?: string }[]
  models?: { status?: string }
  usage?: Record<string, unknown>
  coding?: Record<string, unknown>
}

export type CodingCompleteResult = {
  task: CodingTaskRecord
  conflicts: CodingDecisionInboxItem[]
}

export type CodingIntegrateResult = {
  task_id?: string
  integration_status: string
  requires_approval?: boolean
  conflicts?: CodingDecisionInboxItem[]
  message?: string
  branch?: string
  base_sha?: string
  commits?: string[]
  final_diff?: CodingTaskDiff
  task?: CodingTaskRecord
}

export function codingIntegrationBlocked(result: CodingIntegrateResult): boolean {
  const status = (result.integration_status || "").toLowerCase()
  return status !== "ready"
}

export function formatCodingError(err: unknown): string {
  if (err instanceof Error && err.message) return err.message
  return "Could not update this coding task."
}

export async function getCodingOverview(): Promise<CodingOverview> {
  return api<CodingOverview>("/api/coding")
}

export async function listCodingTasks(activeOnly = false): Promise<{ tasks: CodingTaskRecord[] }> {
  const query = activeOnly ? "?active_only=true" : "?active_only=false"
  return api<{ tasks: CodingTaskRecord[] }>(`/api/coding/tasks${query}`)
}

export async function getCodingTask(taskId: string): Promise<CodingTaskRecord> {
  return api<CodingTaskRecord>(`/api/coding/tasks/${encodeURIComponent(taskId)}`)
}

export async function startCodingTask(body: {
  task_id: string
  repo?: string
}): Promise<CodingTaskRecord> {
  const payload: Record<string, unknown> = { task_id: body.task_id }
  if (body.repo) payload.repo = body.repo
  return api<CodingTaskRecord>("/api/coding/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function completeCodingTask(
  taskId: string,
  tests?: Record<string, unknown>,
): Promise<CodingCompleteResult> {
  return api<CodingCompleteResult>(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/complete`,
    {
      method: "POST",
      body: JSON.stringify({ tests: tests || {} }),
    },
  )
}

export async function approveCodingTask(
  taskId: string,
  approver = "human",
): Promise<CodingTaskRecord> {
  return api<CodingTaskRecord>(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ approver }),
    },
  )
}

export async function integrateCodingTask(taskId: string): Promise<CodingIntegrateResult> {
  return api<CodingIntegrateResult>(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/integrate`,
    { method: "POST" },
  )
}

export async function cleanupCodingTask(taskId: string): Promise<CodingTaskRecord> {
  return api<CodingTaskRecord>(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/cleanup`,
    { method: "POST" },
  )
}

export async function listCodingDecisionInbox(
  openOnly = true,
): Promise<{ items: CodingDecisionInboxItem[] }> {
  const query = openOnly ? "?open_only=true" : "?open_only=false"
  return api<{ items: CodingDecisionInboxItem[] }>(`/api/coding/decision-inbox${query}`)
}

export async function resolveCodingDecisionInboxItem(
  itemId: string,
  resolution: string,
): Promise<CodingDecisionInboxItem> {
  return api<CodingDecisionInboxItem>(
    `/api/coding/decision-inbox/${encodeURIComponent(itemId)}/resolve`,
    {
      method: "POST",
      body: JSON.stringify({ resolution }),
    },
  )
}
