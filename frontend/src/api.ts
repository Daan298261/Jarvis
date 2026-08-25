const AUTH_KEY = "jarvis_auth_token"

export function getAuthToken(): string {
  try {
    return localStorage.getItem(AUTH_KEY) || sessionStorage.getItem(AUTH_KEY) || ""
  } catch {
    return ""
  }
}

export function setAuthToken(token: string): void {
  try {
    const value = token.trim()
    if (value) {
      localStorage.setItem(AUTH_KEY, value)
      sessionStorage.setItem(AUTH_KEY, value)
    } else {
      localStorage.removeItem(AUTH_KEY)
      sessionStorage.removeItem(AUTH_KEY)
    }
  } catch {
    /* private mode */
  }
}

export class AuthError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = "AuthError"
    this.status = status
  }
}

type AuthFailure = { status: number; detail: string }
const authListeners = new Set<(event: AuthFailure) => void>()

export function onAuthFailure(handler: (event: AuthFailure) => void): () => void {
  authListeners.add(handler)
  return () => { authListeners.delete(handler) }
}

function errorMessage(text: string, fallback: string): string {
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed?.detail === "string") return parsed.detail
  } catch {
    /* not JSON */
  }
  return text || fallback
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const token = getAuthToken()
  if (token && !headers.has("X-Jarvis-Token") && !headers.has("Authorization")) {
    headers.set("X-Jarvis-Token", token)
  }
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const text = await response.text()
    const detail = errorMessage(text, response.statusText)
    if (response.status === 401 || response.status === 403) {
      const event = { status: response.status, detail }
      authListeners.forEach((handler) => handler(event))
      throw new AuthError(detail, response.status)
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export async function apiUpload<T>(path: string, body: FormData): Promise<T> {
  const headers = new Headers()
  const token = getAuthToken()
  if (token) headers.set("X-Jarvis-Token", token)
  const response = await fetch(path, { method: "POST", headers, body })
  if (!response.ok) {
    const text = await response.text()
    const detail = errorMessage(text, response.statusText)
    if (response.status === 401 || response.status === 403) {
      const event = { status: response.status, detail }
      authListeners.forEach((handler) => handler(event))
      throw new AuthError(detail, response.status)
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export async function apiWav(path: string, text: string): Promise<Blob> {
  const headers = new Headers({ "Content-Type": "application/json" })
  const token = getAuthToken()
  if (token) headers.set("X-Jarvis-Token", token)
  const response = await fetch(path, { method: "POST", headers, body: JSON.stringify({ text }) })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(errorMessage(body, response.statusText))
  }
  return response.blob()
}

export type TimelineStep = {
  kind: string
  title: string
  detail: string
  stage: string
  created_at?: string | null
  expandable?: boolean
  tool?: string
  backend?: string
  success?: boolean
  error?: string
  duration_ms?: number
  arguments?: string
  stdout?: string
  stderr?: string
  exit_code?: number | null
}

export type Task = {
  id: string
  title: string
  prompt: string
  status: string
  stage: string
  current_action: string
  current_tool: string
  result: string
  error: string
  retries: number
  duration_seconds: number
  created_at: string
  updated_at?: string
  finished_at?: string
  execution_mode?: string
  profile?: string
  task_class?: string
  selected_worker?: string
  waiting_for_confirmation: boolean
  autonomy?: string
  confirmation_payload?: string
  events?: TimelineStep[]
  timeline?: TimelineStep[]
}
