import type { LmStudioCatalogResponse, RuntimeProfile } from "../api"

export type NodeModelOption = { key: string; kind: "runtime" | "catalog" | "file"; id: string; label: string; detail: string; runtimeId?: string }
export function modelName(value: string): string {
  return (value || "").split(/[\\/]/).pop()?.replace(/\.gguf$/i, "") || value
}
export function nodeModelOptions(profiles: RuntimeProfile[], catalog: LmStudioCatalogResponse | null): NodeModelOption[] {
  const options: NodeModelOption[] = [], paths = new Set<string>(), catalogIds = new Set<string>()
  for (const profile of catalog?.profiles || []) {
    if (!profile.path || !profile.matched || paths.has(profile.path.toLowerCase())) continue
    paths.add(profile.path.toLowerCase())
    if (profile.runtime_profile_id) catalogIds.add(profile.runtime_profile_id)
    options.push({ key: `catalog:${profile.id}`, kind: "catalog", id: profile.id,
      label: `${modelName(profile.path)} · ${profile.weight_gb.toFixed(1)} GB`,
      detail: `${profile.weight_gb.toFixed(1)} GB weights · ${profile.quantization} · ${profile.strength || "Local GGUF"}`,
      runtimeId: profile.runtime_profile_id || undefined })
  }
  for (const item of catalog?.ungraded || []) {
    if (!item.path || paths.has(item.path.toLowerCase())) continue
    paths.add(item.path.toLowerCase())
    options.push({ key: `file:${item.path}`, kind: "file", id: item.path,
      label: `${modelName(item.filename)} · ${item.weight_gb.toFixed(1)} GB`,
      detail: `${item.quantization} · Local GGUF · performance and refusal behavior not graded` })
  }
  for (const profile of profiles) {
    if (catalogIds.has(profile.id) || catalogIds.has(profile.name)) continue
    options.push({ key: `runtime:${profile.id}`, kind: "runtime", id: profile.id, runtimeId: profile.id,
      label: `${modelName(profile.model || profile.label || profile.name)} · ${profile.provider}`,
      detail: `${profile.label || profile.name} · ${profile.quantization || "Quantization unspecified"} · configured runtime${profile.is_local ? "" : " · remote"}` })
  }
  return options.sort((a, b) => a.label.localeCompare(b.label))
}
export function selectedModelOption(options: NodeModelOption[], selectedId: string): string {
  return options.find((option) => option.runtimeId === selectedId)?.key || ""
}
export type NodeAiModel = {
  id: string; model: string; display_name: string; model_key?: string; backend: string; port: number; pid?: number;
  verified_loaded: boolean; active: boolean; source: string; roles: string[]; busy?: boolean | null;
  parameters?: string; quantization?: string; context_size?: number; size_bytes?: number;
}
export type NodeAiInventory = {
  node: { id?: string; hostname: string; scope: string }; models: NodeAiModel[];
  servers: { port: number; program: string; pid?: number; verified_loaded: boolean; models: string[]; status: string }[];
  programs: { id: string; name: string; pid: number; process_count: number; category: string; status: string }[];
  checked_at: number; warnings: string[]; coverage: string; read_only: boolean;
}
