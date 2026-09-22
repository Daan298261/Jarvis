import { useState, type FormEvent } from "react"
import { NavLink } from "react-router-dom"
import type { Task } from "../api"
import { TaskHeartbeat } from "../components/TaskActivity"
import { phaseLabel } from "../taskStatus"
import type { PortalProject } from "../projects"

type ChatRow = { conversation_id: string; title: string; project_id?: string }

type ProjectsRailProps = {
  variant: "classic" | "hud"
  projects: PortalProject[]
  tasksById: Map<string, Task>
  chatsById: Map<string, ChatRow>
  ungroupedOwnerChats: ChatRow[]
  recents: Task[]
  currentTaskId?: string
  onCreateProject: (name: string) => Promise<void> | void
  onRenameProject: (projectId: string, name: string) => Promise<void> | void
  onDeleteProject: (projectId: string) => void
  onAssignTask: (projectId: string, taskId: string) => void
  onUnassignTask: (taskId: string) => void
  onAssignChat: (projectId: string, conversationId: string) => void
  onUnassignChat: (conversationId: string) => void
  onAssignRepo: (projectId: string, repoPath: string) => void
  onUnassignRepo: (repoPath: string) => void
  onCloseNav?: () => void
  showRecents?: boolean
}

function taskLabel(task: Task): string {
  return task.title || task.prompt?.slice(0, 72) || "Untitled task"
}

function repoLabel(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean)
  return parts[parts.length - 1] || path
}

export function ProjectsRail({
  variant,
  projects,
  tasksById,
  chatsById,
  ungroupedOwnerChats,
  recents,
  currentTaskId,
  onCreateProject,
  onRenameProject,
  onDeleteProject,
  onAssignTask,
  onUnassignTask,
  onAssignChat,
  onUnassignChat,
  onAssignRepo,
  onUnassignRepo,
  onCloseNav,
  showRecents = true,
}: ProjectsRailProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [newOpen, setNewOpen] = useState(false)
  const [newName, setNewName] = useState("")
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [repoDraft, setRepoDraft] = useState<Record<string, string>>({})

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    const name = newName.trim()
    if (!name) return
    await onCreateProject(name)
    setNewName("")
    setNewOpen(false)
  }

  async function commitRename(event?: FormEvent) {
    event?.preventDefault()
    if (!renamingId) return
    await onRenameProject(renamingId, renameValue)
    setRenamingId(null)
    setRenameValue("")
  }

  return (
    <div className={`projects-rail projects-rail-${variant}`}>
      <section className="rail-section">
        <div className="rail-heading">
          <span>Projects</span>
          <button type="button" className="rail-icon-btn" onClick={() => setNewOpen((open) => !open)}>
            {newOpen ? "Close" : "New"}
          </button>
        </div>
        {newOpen && (
          <form className="rail-inline-form" onSubmit={(event) => void handleCreate(event)}>
            <input
              autoFocus
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="Folder name"
              aria-label="Project name"
            />
          </form>
        )}
        {projects.length === 0 && !newOpen && (
          <p className="rail-empty">Group chats, tasks, and repos under a folder. Names stay on this PC.</p>
        )}
        {projects.map((project) => {
          const open = expanded[project.id] ?? true
          const chats = project.conversationIds || []
          const repos = project.repoPaths || []
          return (
            <div key={project.id} className="rail-project">
              <div className="rail-project-row">
                <button
                  type="button"
                  className="rail-disclosure"
                  aria-expanded={open}
                  onClick={() => setExpanded((prev) => ({ ...prev, [project.id]: !open }))}
                >
                  {open ? "▾" : "▸"}
                </button>
                {renamingId === project.id ? (
                  <form className="rail-inline-form" onSubmit={(event) => void commitRename(event)}>
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={(event) => setRenameValue(event.target.value)}
                      onBlur={() => void commitRename()}
                      aria-label="Rename project"
                    />
                  </form>
                ) : (
                  <button
                    type="button"
                    className="rail-project-name"
                    onClick={() => setExpanded((prev) => ({ ...prev, [project.id]: !open }))}
                    onDoubleClick={() => {
                      setRenamingId(project.id)
                      setRenameValue(project.name)
                    }}
                  >
                    {project.name}
                  </button>
                )}
                {currentTaskId && !project.taskIds.includes(currentTaskId) && (
                  <button
                    type="button"
                    className="rail-icon-btn"
                    title="Add this task"
                    onClick={() => onAssignTask(project.id, currentTaskId)}
                  >
                    Add
                  </button>
                )}
                <button
                  type="button"
                  className="rail-icon-btn"
                  title="Rename"
                  onClick={() => {
                    setRenamingId(project.id)
                    setRenameValue(project.name)
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="rail-icon-btn"
                  title="Remove project"
                  onClick={() => onDeleteProject(project.id)}
                >
                  ×
                </button>
              </div>
              {open && (
                <div className="rail-project-tasks">
                  {chats.map((conversationId) => {
                    const chatRow = chatsById.get(conversationId)
                    return (
                      <div key={`chat-${conversationId}`} className="rail-item-row">
                        <NavLink to={`/chats/${conversationId}`} className="rail-item" onClick={onCloseNav}>
                          <span className="rail-item-title">{chatRow?.title || "Chat"}</span>
                          <span className="rail-item-meta">Chat</span>
                        </NavLink>
                        <button
                          type="button"
                          className="rail-icon-btn"
                          title="Remove chat from project"
                          onClick={() => onUnassignChat(conversationId)}
                        >
                          ×
                        </button>
                      </div>
                    )
                  })}
                  {project.taskIds.map((taskId) => {
                    const task = tasksById.get(taskId)
                    return (
                      <div key={taskId} className="rail-item-row">
                        <NavLink
                          to={`/tasks/${taskId}`}
                          className={({ isActive }) => `rail-item${isActive ? " active" : ""}`}
                          onClick={onCloseNav}
                        >
                          <span className="rail-item-title">{task ? taskLabel(task) : "Open task"}</span>
                          {task && ["queued", "running", "waiting"].includes(task.state || task.status) && (
                            <span className="rail-item-meta">
                              <TaskHeartbeat task={task} label={false} />
                              {phaseLabel(task)}
                            </span>
                          )}
                        </NavLink>
                        <button
                          type="button"
                          className="rail-icon-btn"
                          title="Remove from project"
                          onClick={() => onUnassignTask(taskId)}
                        >
                          ×
                        </button>
                      </div>
                    )
                  })}
                  {repos.map((path) => (
                    <div key={`repo-${path}`} className="rail-item-row">
                      <span className="rail-item rail-item-static" title={path}>
                        <span className="rail-item-title">{repoLabel(path)}</span>
                        <span className="rail-item-meta">Repo</span>
                      </span>
                      <button
                        type="button"
                        className="rail-icon-btn"
                        title="Remove repo from project"
                        onClick={() => onUnassignRepo(path)}
                      >
                        ×
                      </button>
                    </div>
                  ))}
                  <form
                    className="rail-inline-form"
                    onSubmit={(event) => {
                      event.preventDefault()
                      const path = (repoDraft[project.id] || "").trim()
                      if (!path) return
                      onAssignRepo(project.id, path)
                      setRepoDraft((prev) => ({ ...prev, [project.id]: "" }))
                    }}
                  >
                    <input
                      value={repoDraft[project.id] || ""}
                      onChange={(event) =>
                        setRepoDraft((prev) => ({ ...prev, [project.id]: event.target.value }))
                      }
                      placeholder="Add repo path"
                      aria-label={`Add repository path to ${project.name}`}
                    />
                  </form>
                  {project.taskIds.length === 0 && chats.length === 0 && repos.length === 0 && (
                    <p className="rail-empty">No tasks, chats, or repos in this folder yet.</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </section>

      {ungroupedOwnerChats.length > 0 && (
        <section className="rail-section">
          <div className="rail-heading">
            <span>Saved chats</span>
          </div>
          {ungroupedOwnerChats.slice(0, 16).map((chatRow) => (
            <div key={chatRow.conversation_id} className="rail-item-row">
              <NavLink to={`/chats/${chatRow.conversation_id}`} className="rail-item" onClick={onCloseNav}>
                <span className="rail-item-title">{chatRow.title || "Chat"}</span>
                <span className="rail-item-meta">Chat</span>
              </NavLink>
              {projects.length > 0 && (
                <select
                  className="rail-assign"
                  aria-label={`Move ${chatRow.title || "chat"} to a project`}
                  value=""
                  onChange={(event) => {
                    const value = event.target.value
                    if (value) onAssignChat(value, chatRow.conversation_id)
                  }}
                >
                  <option value="">Move…</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          ))}
        </section>
      )}

      {showRecents && (
        <section className="rail-section">
          <div className="rail-heading">
            <span>Recents</span>
          </div>
          {recents.length === 0 && <p className="rail-empty">No tasks yet. Start from New task.</p>}
          {recents.slice(0, 24).map((task) => {
            const grouped = projects.find((project) => project.taskIds.includes(task.id))
            return (
              <div key={task.id} className="rail-item-row">
                <NavLink
                  to={`/tasks/${task.id}`}
                  className={({ isActive }) => `rail-item${isActive ? " active" : ""}`}
                  onClick={onCloseNav}
                >
                  <span className="rail-item-title">{taskLabel(task)}</span>
                  <span className="rail-item-meta">
                    {["queued", "running", "waiting"].includes(task.state || task.status) && (
                      <TaskHeartbeat task={task} label={false} />
                    )}
                    {phaseLabel(task)}
                    {grouped ? ` · ${grouped.name}` : ""}
                  </span>
                </NavLink>
                {projects.length > 0 && (
                  <select
                    className="rail-assign"
                    aria-label={`Move ${taskLabel(task)} to a project`}
                    value={grouped?.id || ""}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => {
                      const value = event.target.value
                      if (!value) onUnassignTask(task.id)
                      else onAssignTask(value, task.id)
                    }}
                  >
                    <option value="">—</option>
                    {projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )
          })}
        </section>
      )}
    </div>
  )
}
