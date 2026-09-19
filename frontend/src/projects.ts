import { api } from "./api"

export type PortalProject = {
  id: string
  name: string
  taskIds: string[]
  conversationIds?: string[]
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
  return { id: row.id, name: row.name.trim(), taskIds, conversationIds }
}

export function loadProjectsLocal(): PortalProject[] {
  const store = storage()
  if (!store) return []
  try {
    const raw = store.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as Partial<PortalProjectStore>
    if (!Array.isArray(parsed?.projects)) return []
    return parsed.projects.map(asProject).filter((row): row is PortalProject => row !== null)
  } catch {
    return []
  }
}

export function saveProjectsLocal(projects: PortalProject[]): void {
  const store = storage()
  if (!store) return
  try {
    const payload: PortalProjectStore = { version: 1, projects }
    store.setItem(STORAGE_KEY, JSON.stringify(payload))
  } catch {
    // ignore quota / private-mode failures
  }
}

/** Leader DB is canonical; localStorage is a one-time migration source. */
export async function fetchProjects(): Promise<PortalProject[]> {
  try {
    const payload = await api<{ projects: PortalProject[] }>("/api/projects")
    const remote = (payload.projects || []).map(asProject).filter((row): row is PortalProject => row !== null)
    if (remote.length > 0) {
      saveProjectsLocal(remote)
      return remote
    }
    const local = loadProjectsLocal()
    if (local.length > 0) {
      const imported = await api<{ projects: PortalProject[] }>("/api/projects/import-local", {
        method: "POST",
        body: JSON.stringify({ projects: local }),
      })
      return (imported.projects || []).map(asProject).filter((row): row is PortalProject => row !== null)
    }
    return []
  } catch {
    return loadProjectsLocal()
  }
}

export async function persistProjects(projects: PortalProject[]): Promise<void> {
  saveProjectsLocal(projects)
}

export async function createProjectRemote(name: string): Promise<PortalProject | null> {
  try {
    return await api<PortalProject>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    })
  } catch {
    return null
  }
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
  linkType: "task" | "owner_chat",
  linkId: string,
): Promise<void> {
  await api(`/api/projects/${encodeURIComponent(projectId)}/links`, {
    method: "POST",
    body: JSON.stringify({ link_type: linkType, link_id: linkId }),
  })
}

export async function unlinkProjectMember(linkType: "task" | "owner_chat", linkId: string): Promise<void> {
  await api(`/api/projects/links/${encodeURIComponent(linkType)}/${encodeURIComponent(linkId)}`, {
    method: "DELETE",
  })
}

export function createProject(name: string, projects: PortalProject[]): PortalProject[] {
  const trimmed = name.trim()
  if (!trimmed) return projects
  const next: PortalProject = {
    id: crypto.randomUUID(),
    name: trimmed,
    taskIds: [],
    conversationIds: [],
  }
  return [...projects, next]
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

export function projectForTask(taskId: string, projects: PortalProject[]): PortalProject | undefined {
  return projects.find((project) => project.taskIds.includes(taskId))
}

/** @deprecated use fetchProjects */
export function loadProjects(): PortalProject[] {
  return loadProjectsLocal()
}

/** @deprecated use persistProjects */
export function saveProjects(projects: PortalProject[]): void {
  saveProjectsLocal(projects)
}
