import { api } from "../api"

export type VaultPublicStatus = {
  bound: boolean
  jarvis_managed_layout: boolean
  bound_at: string
  last_index_at: string
  note_count: number
}

export type VaultHealthResponse = {
  binding: VaultPublicStatus
  broken_links: Array<{ source: string; target: string }>
  duplicate_ids: Array<Record<string, unknown>>
  stale_index_paths: string[]
  missing_router: boolean
}

const VAULT_PATH_CACHE_KEY = "jarvis.knowledge_vault.path"

export function cacheVaultPathForDesktop(path: string): void {
  try {
    if (path.trim()) {
      localStorage.setItem(VAULT_PATH_CACHE_KEY, path.trim())
    } else {
      localStorage.removeItem(VAULT_PATH_CACHE_KEY)
    }
  } catch {
    /* ignore */
  }
}

export function readCachedVaultPath(): string {
  try {
    return localStorage.getItem(VAULT_PATH_CACHE_KEY) || ""
  } catch {
    return ""
  }
}

export async function fetchVaultStatus(): Promise<VaultPublicStatus> {
  return api<VaultPublicStatus>("/api/vault/status")
}

export async function fetchVaultHealth(): Promise<VaultHealthResponse> {
  return api<VaultHealthResponse>("/api/vault/health")
}

export async function bindVault(vaultPath: string, initLayout = false): Promise<unknown> {
  const result = await api("/api/vault/bind", {
    method: "POST",
    body: JSON.stringify({ vault_path: vaultPath, init_layout: initLayout }),
  })
  cacheVaultPathForDesktop(vaultPath)
  return result
}

export async function unbindVault(): Promise<unknown> {
  const result = await api("/api/vault/unbind", { method: "POST", body: "{}" })
  cacheVaultPathForDesktop("")
  return result
}
