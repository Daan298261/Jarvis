export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || response.statusText)
  }
  return response.json() as Promise<T>
}

export type Task = {
  id: string
  title: string
  prompt: string
  status: string
  stage: string
  execution_mode?: string
  task_class?: string
  acceptance_criteria?: string
  current_action: string
  current_tool: string
  result: string
  error: string
  verification?: string
  retries: number
  duration_seconds: number
  created_at: string
  waiting_for_confirmation: boolean
  events?: { kind: string; title: string; detail: string; stage: string; created_at: string }[]
}
