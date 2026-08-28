import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom"
import { useEffect, useMemo, useState, type FormEvent } from "react"
import { ChatPage } from "./pages/Chat"
import { HistoryPage } from "./pages/History"
import { MemoryPage } from "./pages/Memory"
import { ModelPage } from "./pages/Model"
import { ToolsPage } from "./pages/Tools"
import { McpPage } from "./pages/Mcp"
import { SettingsPage } from "./pages/Settings"
import { SystemPage } from "./pages/System"
import { SwarmPage } from "./pages/Swarm"
import { WorkflowsPage } from "./pages/Workflows"
import { PhonePage } from "./pages/Phone"
import { AgentsPage } from "./pages/Agents"
import { AgentInterviewPage } from "./pages/AgentInterview"
import { GuestPortalsPage } from "./pages/GuestPortals"
import { GuestPage } from "./pages/Guest"
import { PacksPage } from "./pages/Packs"
import { api, getAwayMode, type AwayModeState, type Task } from "./api"
import {
  assignTask,
  createProject,
  deleteProject,
  loadProjects,
  projectForTask,
  renameProject,
  saveProjects,
  unassignTask,
  type PortalProject,
} from "./projects"

const WORK_LINKS = [
  { to: "/history", label: "History" },
  { to: "/workflows", label: "Guide & Workflows" },
  { to: "/memory", label: "Memory" },
  { to: "/phone", label: "Phone" },
] as const

const ADMIN_LINKS = [
  { to: "/settings", label: "Settings" },
  { to: "/guest-portals", label: "Guest portals" },
  { to: "/agents", label: "Agents" },
  { to: "/packs", label: "Packs" },
  { to: "/model", label: "Model" },
  { to: "/tools", label: "Tools" },
  { to: "/mcp", label: "MCP" },
  { to: "/system", label: "System" },
  { to: "/swarm", label: "Swarm" },
] as const

function isChatPath(pathname: string): boolean {
  return pathname === "/" || pathname.startsWith("/tasks/")
}

function isAdminPath(pathname: string): boolean {
  return ADMIN_LINKS.some((link) => pathname === link.to || pathname.startsWith(`${link.to}/`))
}

function isGuestPath(pathname: string): boolean {
  return pathname === "/guest" || pathname.startsWith("/guest/")
}

function activeTaskId(pathname: string): string | undefined {
  const match = pathname.match(/^\/tasks\/([^/]+)/)
  return match?.[1]
}

function taskLabel(task: Task): string {
  return task.title || task.prompt?.slice(0, 72) || "Untitled task"
}

export default function App() {
  const location = useLocation()
  if (isGuestPath(location.pathname)) {
    return <GuestPage />
  }
  return <OwnerPortal />
}

function OwnerPortal() {
  const location = useLocation()
  const [model, setModel] = useState<any>(null)
  const [away, setAway] = useState<AwayModeState | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [recents, setRecents] = useState<Task[]>([])
  const [projects, setProjects] = useState<PortalProject[]>(() => loadProjects())
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [newProjectName, setNewProjectName] = useState("")
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [adminOpen, setAdminOpen] = useState(false)

  const chat = isChatPath(location.pathname)
  const currentTaskId = activeTaskId(location.pathname)
  const showAdmin = adminOpen || isAdminPath(location.pathname)

  useEffect(() => {
    const tick = () => api<any>("/api/model").then(setModel).catch(() => undefined)
    tick()
    const id = window.setInterval(tick, 8000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    const tick = () => getAwayMode().then(setAway).catch(() => undefined)
    tick()
    const id = window.setInterval(tick, 8000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    const tick = () => api<Task[]>("/api/tasks").then(setRecents).catch(() => undefined)
    tick()
    const id = window.setInterval(tick, 4000)
    return () => window.clearInterval(id)
  }, [location.pathname])

  useEffect(() => {
    saveProjects(projects)
  }, [projects])

  const tasksById = useMemo(() => {
    const map = new Map<string, Task>()
    for (const task of recents) map.set(task.id, task)
    return map
  }, [recents])

  function closeNav() {
    setNavOpen(false)
  }

  function updateProjects(next: PortalProject[]) {
    setProjects(next)
    saveProjects(next)
  }

  function handleCreateProject(event: FormEvent) {
    event.preventDefault()
    const next = createProject(newProjectName, projects)
    if (next !== projects) {
      const created = next[next.length - 1]
      updateProjects(next)
      setExpanded((prev) => ({ ...prev, [created.id]: true }))
    }
    setNewProjectName("")
    setNewProjectOpen(false)
  }

  function commitRename(event?: FormEvent) {
    event?.preventDefault()
    if (!renamingId) return
    updateProjects(renameProject(renamingId, renameValue, projects))
    setRenamingId(null)
    setRenameValue("")
  }

  function modelStatus(): { label: string; tone: string } {
    if (model?.loaded) return { label: "Ready", tone: "on" }
    if (model?.loading) return { label: "Starting", tone: "load" }
    return { label: "Model off", tone: "off" }
  }

  const status = modelStatus()

  return (
    <div className={`app${navOpen ? " nav-open" : ""}${chat ? " chat-shell" : ""}`}>
      <header className="mobile-bar">
        <button className="nav-toggle" type="button" aria-label="Open menu" onClick={() => setNavOpen((open) => !open)}>
          Menu
        </button>
        <strong>JARVIS</strong>
        <span className={`dot ${status.tone}`} />
      </header>
      {navOpen && <button className="nav-backdrop" type="button" aria-label="Close menu" onClick={closeNav} />}
      <aside className="sidebar">
        <div className="brand">
          <strong>JARVIS</strong>
          <span>On this PC</span>
        </div>

        <NavLink to="/" end className="rail-new" onClick={closeNav}>
          New task
        </NavLink>

        <section className="rail-section">
          <div className="rail-heading">
            <span>Projects</span>
            <button type="button" className="rail-icon-btn" onClick={() => setNewProjectOpen((open) => !open)}>
              {newProjectOpen ? "Close" : "New"}
            </button>
          </div>
          {newProjectOpen && (
            <form className="rail-inline-form" onSubmit={handleCreateProject}>
              <input
                autoFocus
                value={newProjectName}
                onChange={(event) => setNewProjectName(event.target.value)}
                placeholder="Project name"
                aria-label="Project name"
              />
            </form>
          )}
          {projects.length === 0 && !newProjectOpen && (
            <p className="rail-empty">Group related tasks. Names stay on this PC.</p>
          )}
          {projects.map((project) => {
            const open = expanded[project.id] ?? true
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
                    <form className="rail-inline-form" onSubmit={commitRename}>
                      <input
                        autoFocus
                        value={renameValue}
                        onChange={(event) => setRenameValue(event.target.value)}
                        onBlur={() => commitRename()}
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
                      onClick={() => updateProjects(assignTask(project.id, currentTaskId, projects))}
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
                    onClick={() => updateProjects(deleteProject(project.id, projects))}
                  >
                    ×
                  </button>
                </div>
                {open && (
                  <div className="rail-project-tasks">
                    {project.taskIds.length === 0 && (
                      <p className="rail-empty">No tasks in this project yet.</p>
                    )}
                    {project.taskIds.map((taskId) => {
                      const task = tasksById.get(taskId)
                      return (
                        <div key={taskId} className="rail-item-row">
                          <NavLink
                            to={`/tasks/${taskId}`}
                            className={({ isActive }) => `rail-item${isActive ? " active" : ""}`}
                            onClick={closeNav}
                          >
                            {task ? taskLabel(task) : "Open task"}
                          </NavLink>
                          <button
                            type="button"
                            className="rail-icon-btn"
                            title="Remove from project"
                            onClick={() => updateProjects(unassignTask(taskId, projects))}
                          >
                            ×
                          </button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </section>

        <section className="rail-section">
          <div className="rail-heading">
            <span>Recents</span>
          </div>
          {recents.length === 0 && <p className="rail-empty">No tasks yet. Start from New task.</p>}
          {recents.slice(0, 24).map((task) => {
            const grouped = projectForTask(task.id, projects)
            return (
              <div key={task.id} className="rail-item-row">
                <NavLink
                  to={`/tasks/${task.id}`}
                  className={({ isActive }) => `rail-item${isActive ? " active" : ""}`}
                  onClick={closeNav}
                >
                  <span className="rail-item-title">{taskLabel(task)}</span>
                  {grouped && <span className="rail-item-meta">{grouped.name}</span>}
                </NavLink>
                {projects.length > 0 && (
                  <select
                    className="rail-assign"
                    aria-label={`Move ${taskLabel(task)} to a project`}
                    value={grouped?.id || ""}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => {
                      const value = event.target.value
                      if (!value) updateProjects(unassignTask(task.id, projects))
                      else updateProjects(assignTask(value, task.id, projects))
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

        <nav className="rail-work" onClick={closeNav}>
          {WORK_LINKS.map((link) => (
            <NavLink key={link.to} to={link.to}>
              {link.label}
            </NavLink>
          ))}
        </nav>

        <div className="rail-admin">
          <div className="rail-project-row">
            <NavLink
              to="/settings"
              className={({ isActive }) => `rail-item${isActive ? " active" : ""}`}
              onClick={closeNav}
            >
              Settings
            </NavLink>
            <button
              type="button"
              className="rail-icon-btn"
              aria-expanded={showAdmin}
              aria-label="Show more settings"
              onClick={() => setAdminOpen((open) => !open)}
            >
              {showAdmin ? "▾" : "▸"}
            </button>
          </div>
          {showAdmin && (
            <nav className="rail-admin-links" onClick={closeNav}>
              {ADMIN_LINKS.filter((link) => link.to !== "/settings").map((link) => (
                <NavLink key={link.to} to={link.to}>
                  {link.label}
                </NavLink>
              ))}
            </nav>
          )}
        </div>

        <p className="tray-hint">
          To stop Jarvis, use <strong>Stop</strong> on the Windows tray. This window is for talking and settings.
        </p>
        <div className="side-status">
          <div>
            <span className={`dot ${status.tone}`} />
            {status.label}
          </div>
          {model?.active_model && <div className="side-status-meta">{model.active_model}</div>}
          {away?.enabled && (
            <div className="side-status-meta">
              Away Mode{away.pause_proactivity ? " — new work paused" : ""}
            </div>
          )}
        </div>
      </aside>
      <main className={`main${chat ? " chat-main" : ""}`}>
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/phone" element={<PhonePage />} />
          <Route path="/tasks/:id" element={<ChatPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/model" element={<ModelPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/mcp" element={<McpPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/guest-portals" element={<GuestPortalsPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/agents/new" element={<AgentInterviewPage />} />
          <Route path="/agents/:id" element={<AgentInterviewPage />} />
          <Route path="/packs" element={<PacksPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/swarm" element={<SwarmPage />} />
          <Route path="/swarm/:nodeId" element={<SwarmPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
