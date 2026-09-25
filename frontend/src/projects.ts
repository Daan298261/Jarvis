import { api, isApiError } from "./api"

export type PortalProject = {
  id: string
  name: string
  taskIds: string[]
  conversationIds?: string[]
  repoPaths?: string[]
}

export type FetchProjectsResult = {
  projects: PortalProject[]
  /** True when browser localStorage groupings were migrated via import-local. */
  migratedFromLocal: boolean
}

type PortalProjectStore = {
  version: 1
  projects: PortalProject[]
}

const STORAGE_KEY = "jarvis_portal_projects"

function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function asProject(value: unknown): PortalProject | null {
  if (!value || typeof value !== "object") return null
  const row = value as Partial<PortalProject>
  if (typeof row.id !== "string" || !row.id) return null
  if (typeof row.name !== "string" || !row.name.trim()) return null
  const taskIds = Array.isArray(row.taskIds)
    ? row.taskIds.filter((id): id is string => typeof id === "string" && id.length > 0)
    : []
  const conversationIds = Array.isArray(row.conversationIds)
    ? row.conversationIds.filter((id): id is string => typeof id === "string" && id.length > 0)
    : []
  const repoPaths = Array.isArray(row.repoPaths)
    ? row.repoPaths.filter((id): id is string => typeof id === "string" && id.trim().length > 0)
    : []
  return { id: row.id, name: row.name.trim(), taskIds, conversationIds, repoPaths }
}

function loadProjectsLocal(): PortalProject[] {
  const store = storage()
  if (!store) return []
  try {
    const raw = store.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as Partial<PortalProjectStore>
    if (!Array.isArray(parsed?.projects)) {
      clearProjectsLocal()
      return []
    }
    const projects = parsed.projects.map(asProject).filter((row): row is PortalProject => row !== null)
    if (projects.length === 0) clearProjectsLocal()
    return projects
  } catch {
    clearProjectsLocal()
    return []
  }
}

function clearProjectsLocal(): void {
  const store = storage()
  if (!store) return
  try {
    store.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}

function parseProjectList(value: unknown): PortalProject[] {
  if (!Array.isArray(value)) return []
  return value.map(asProject).filter((row): row is PortalProject => row !== null)
}

/**
 * Leader DB is canonical. `jarvis_portal_projects` is read only to migrate
 * folders the Leader does not already have, then cleared. It is never written
 * and never returned as the rail when import fails.
 */
export async function fetchProjects(): Promise<FetchProjectsResult> {
  const payload = await api<{ projects?: unknown }>("/api/projects")
  const remote = parseProjectList(payload?.projects)
  const local = loadProjectsLocal()
  if (local.length === 0) {
    return { projects: remote, migratedFromLocal: false }
  }

  const remoteIds = new Set(remote.map((project) => project.id))
  const pending = local.filter((project) => !remoteIds.has(project.id))
  if (pending.length === 0) {
    clearProjectsLocal()
    return { projects: remote, migratedFromLocal: false }
  }

  const imported = await api<{ projects?: unknown }>("/api/projects/import-local", {
    method: "POST",
    body: JSON.stringify({ projects: pending }),
  })
  const projects = parseProjectList(imported?.projects)
  const importedIds = new Set(projects.map((project) => project.id))
  if (pending.some((project) => !importedIds.has(project.id))) {
    throw new Error("Could not import browser project folders into Jarvis.")
  }
  clearProjectsLocal()
  return { projects, migratedFromLocal: true }
}

export function projectsFetchErrorMessage(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 401) {
      return "Authentication required. Add your owner key in Settings or open Jarvis on this PC."
    }
    return err.message || `Projects API failed (${err.status})`
  }
  if (err instanceof Error && err.message) return err.message
  return "Could not load projects from Jarvis."
}

export async function createProjectRemote(name: string): Promise<PortalProject> {
  const row = await api<PortalProject>("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  })
  const project = asProject(row)
  if (!project) throw new Error("Invalid project response from server")
  return project
}

export async function renameProjectRemote(projectId: string, name: string): Promise<void> {
  await api(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  })
}

export async function deleteProjectRemote(projectId: string): Promise<void> {
  await api(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" })
}

export async function linkProjectMember(
  projectId: string,
  linkType: "task" | "owner_chat" | "repo",
  linkId: string,
): Promise<void> {
  await api(`/api/projects/${encodeURIComponent(projectId)}/links`, {
    method: "POST",
    body: JSON.stringify({ link_type: linkType, link_id: linkId }),
  })
}

export async function unlinkProjectMember(
  linkType: "task" | "owner_chat" | "repo",
  linkId: string,
): Promise<void> {
  const query = new URLSearchParams({ link_type: linkType, link_id: linkId })
  await api(`/api/projects/unlink?${query.toString()}`, { method: "DELETE" })
}

/** Merge link-table chats with legacy conversation.project_id rows for rail display. */
export function enrichProjectsWithOwnerChats(
  projects: PortalProject[],
  ownerChats: { conversation_id: string; project_id?: string }[],
): PortalProject[] {
  if (ownerChats.length === 0) return projects
  return projects.map((project) => {
    const ids = new Set(project.conversationIds || [])
    for (const chat of ownerChats) {
      if (chat.project_id === project.id) ids.add(chat.conversation_id)
    }
    return { ...project, conversationIds: [...ids] }
  })
}

export function renameProject(projectId: string, name: string, projects: PortalProject[]): PortalProject[] {
  const trimmed = name.trim()
  if (!trimmed) return projects
  return projects.map((project) => (project.id === projectId ? { ...project, name: trimmed } : project))
}

export function deleteProject(projectId: string, projects: PortalProject[]): PortalProject[] {
  return projects.filter((project) => project.id !== projectId)
}

export function assignTask(projectId: string, taskId: string, projects: PortalProject[]): PortalProject[] {
  return projects.map((project) => {
    const without = project.taskIds.filter((id) => id !== taskId)
    if (project.id === projectId) {
      return { ...project, taskIds: [...without, taskId] }
    }
    return { ...project, taskIds: without }
  })
}

export function unassignTask(taskId: string, projects: PortalProject[]): PortalProject[] {
  return projects.map((project) => ({
    ...project,
    taskIds: project.taskIds.filter((id) => id !== taskId),
  }))
}

export function assignConversation(
  projectId: string,
  conversationId: string,
  projects: PortalProject[],
): PortalProject[] {
  return projects.map((project) => {
    const without = (project.conversationIds || []).filter((id) => id !== conversationId)
    if (project.id === projectId) {
      return { ...project, conversationIds: [...without, conversationId] }
    }
    return { ...project, conversationIds: without }
  })
}

export function unassignConversation(conversationId: string, projects: PortalProject[]): PortalProject[] {
  return projects.map((project) => ({
    ...project,
    conversationIds: (project.conversationIds || []).filter((id) => id !== conversationId),
  }))
}

export function assignRepo(projectId: string, repoPath: string, projects: PortalProject[]): PortalProject[] {
  const path = repoPath.trim()
  if (!path) return projects
  return projects.map((project) => {
    const without = (project.repoPaths || []).filter((id) => id !== path)
    if (project.id === projectId) {
      return { ...project, repoPaths: [...without, path] }
    }
    return { ...project, repoPaths: without }
  })
}

export function unassignRepo(repoPath: string, projects: PortalProject[]): PortalProject[] {
  return projects.map((project) => ({
    ...project,
    repoPaths: (project.repoPaths || []).filter((id) => id !== repoPath),
  }))
}

export function projectForTask(taskId: string, projects: PortalProject[]): PortalProject | undefined {
  return projects.find((project) => project.taskIds.includes(taskId))
}
