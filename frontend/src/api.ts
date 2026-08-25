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
  exposed_tools?: string[]
  result: string
  error: string
  verification?: string
  retries: number
  duration_seconds: number
  started_at?: string | null
  created_at: string
  waiting_for_confirmation: boolean
  events?: { kind: string; title: string; detail: string; stage: string; created_at: string }[]
}
