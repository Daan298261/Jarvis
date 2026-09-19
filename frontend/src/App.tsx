import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { ChatPage } from "./pages/Chat"
import { HistoryPage } from "./pages/History"
import { MemoryPage } from "./pages/Memory"
import { ObsidianPage } from "./pages/Obsidian"
import { ModelPage } from "./pages/Model"
import { ToolsPage } from "./pages/Tools"
import { McpPage } from "./pages/Mcp"
import { SettingsPage } from "./pages/Settings"
import { SystemPage } from "./pages/System"
import { SwarmPage } from "./pages/Swarm"
import { WorkflowsPage } from "./pages/Workflows"
import { PhonePage } from "./pages/Phone"
import { SetupPage } from "./pages/Setup"
import { AgentsPage } from "./pages/Agents"
import { AgentInterviewPage } from "./pages/AgentInterview"
import { GuestPortalsPage } from "./pages/GuestPortals"
import { GuestPage } from "./pages/Guest"
import { PacksPage } from "./pages/Packs"
import { AdsPage } from "./pages/Ads"
import { WorkerEnvironmentsPage } from "./pages/WorkerEnvironments"
import { DelegationPage } from "./pages/Delegation"
import { LicensePage } from "./pages/License"
import { AdvisorPage } from "./pages/Advisor"
import { ContextRepoPage } from "./pages/ContextRepo"
import { TrajectoriesPage } from "./pages/Trajectories"
import { PortabilityPage } from "./pages/Portability"
import { CodingPage } from "./pages/Coding"
import { api, getAwayMode, getDiagnostics, getLicenseStatus, getSetupStatus, listCodingDecisionInbox, listSwarmNodes, type AwayModeState, type LicenseStatus, type SwarmNode, type Task } from "./api"
import { DesktopBridge, type BackendLifecycleStatus } from "./desktop/bridge"
import { HelpPanel, HelpTrigger } from "./help/HelpPanel"
import { PortalNav } from "./components/PortalNav"
import { BootNova } from "./boot/BootNova"
import { HudShell } from "./hud/HudShell"
import { PendingApprovalHost } from "./chat/PendingApprovalHost"
import { PendingApprovalsProvider } from "./chat/pendingApprovals"
import { HudChatHome } from "./hud/HudChatHome"
import { getUiMode, setUiMode as persistUiMode, type UiMode } from "./hud/uiMode"
import "./hud/hud.css"
import { TaskHeartbeat } from "./components/TaskActivity"
import { phaseLabel } from "./taskStatus"
import {
  assignTask,
  createProject,
  createProjectRemote,
  deleteProject,
  deleteProjectRemote,
  fetchProjects,
  linkProjectMember,
  persistProjects,
  projectForTask,
  renameProject,
  renameProjectRemote,
  unlinkProjectMember,
  unassignTask,
  type PortalProject,
} from "./projects"

const WORK_LINKS = [
  { to: "/history", label: "History" },
  { to: "/workflows", label: "Guide & Workflows" },
  { to: "/obsidian", label: "Obsidian" },
  { to: "/memory", label: "Memory" },
  { to: "/phone", label: "Phone" },
] as const

const ADMIN_LINKS = [
  { to: "/settings", label: "Settings" },
  { to: "/license", label: "License" },
  { to: "/advisor", label: "Advisor" },
  { to: "/guest-portals", label: "Guest portals" },
  { to: "/agents", label: "Agents" },
  { to: "/portability", label: "Portability" },
  { to: "/context", label: "Context" },
  { to: "/trajectories", label: "Trajectories" },
  { to: "/environments", label: "Environments" },
  { to: "/coding", label: "Coding" },
  { to: "/packs", label: "Packs" },
  { to: "/ads", label: "Amazon Ads" },
  { to: "/delegation", label: "Helpers" },
  { to: "/model", label: "Model" },
  { to: "/tools", label: "Tools" },
  { to: "/mcp", label: "Connections" },
  { to: "/system", label: "System" },
  { to: "/swarm", label: "Swarm" },
] as const

function isChatPath(pathname: string): boolean {
  return pathname === "/" || pathname.startsWith("/tasks/")
}

function isAdminPath(pathname: string): boolean {
  if (pathname === "/settings" || pathname.startsWith("/settings/")) return true
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
  return (
    <PendingApprovalsProvider>
      <OwnerPortal />
      <PendingApprovalHost />
    </PendingApprovalsProvider>
  )
}

function OwnerPortal() {
  const location = useLocation()
  const navigate = useNavigate()
  const [model, setModel] = useState<any>(null)
  const [away, setAway] = useState<AwayModeState | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null)
  const [shellStatus, setShellStatus] = useState<BackendLifecycleStatus>("unknown")
  const [recents, setRecents] = useState<Task[]>([])
  const [projects, setProjects] = useState<PortalProject[]>([])
  const [ownerChats, setOwnerChats] = useState<{ conversation_id: string; title: string; project_id?: string }[]>([])
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [newProjectName, setNewProjectName] = useState("")
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [adminOpen, setAdminOpen] = useState(false)
  const [uiMode, setUiModeState] = useState<UiMode>(() => getUiMode())
  const [license, setLicense] = useState<LicenseStatus | null>(null)
  const [swarmNodes, setSwarmNodes] = useState<SwarmNode[]>([])
  const [decisionInboxCount, setDecisionInboxCount] = useState(0)
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null)

  const setUiMode = useCallback((mode: UiMode) => {
    setUiModeState(mode)
    persistUiMode(mode)
  }, [])

  const chat = isChatPath(location.pathname)
  const currentTaskId = activeTaskId(location.pathname)
  const showAdmin = adminOpen || isAdminPath(location.pathname)
  const isSetup = location.pathname.startsWith("/setup")

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
    fetchProjects().then(setProjects).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (projects.length === 0) return
    persistProjects(projects).catch(() => undefined)
  }, [projects])

  useEffect(() => {
    const tick = () =>
      api<{ conversations: { conversation_id: string; title: string; project_id?: string }[] }>(
        "/api/owner/chat/conversations",
      )
        .then((payload) => setOwnerChats(payload.conversations || []))
        .catch(() => undefined)
    tick()
    const id = window.setInterval(tick, 8000)
    return () => window.clearInterval(id)
  }, [location.pathname])

  useEffect(() => {
    getSetupStatus()
      .then((status) => {
        setNeedsSetup(status.needs_setup)
        if (
          status.needs_setup &&
          !location.pathname.startsWith("/setup") &&
          !location.pathname.startsWith("/phone")
        ) {
          navigate("/setup", { replace: true })
        }
      })
      .catch(() => setNeedsSetup(false))
  }, [location.pathname, navigate])

  useEffect(() => {
    if (!DesktopBridge.isDesktop()) return
    const tick = () => DesktopBridge.backendStatus().then(setShellStatus).catch(() => undefined)
    tick()
    const id = window.setInterval(tick, 4000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    if (uiMode !== "hud") return
    const tick = () => {
      getLicenseStatus().then(setLicense).catch(() => undefined)
      listSwarmNodes()
        .then((res) => setSwarmNodes(res.nodes || []))
        .catch(() => undefined)
      listCodingDecisionInbox(true)
        .then((res) => setDecisionInboxCount(res.items?.length || 0))
        .catch(() => undefined)
      getDiagnostics().then(setDiagnostics).catch(() => undefined)
    }
    tick()
    const id = window.setInterval(tick, 8000)
    return () => window.clearInterval(id)
  }, [uiMode])

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
    persistProjects(next).catch(() => undefined)
  }

  async function handleCreateProject(event: FormEvent) {
    event.preventDefault()
    const remote = await createProjectRemote(newProjectName)
    const created = remote || createProject(newProjectName, projects).slice(-1)[0]
    if (created) {
      updateProjects([...projects.filter((p) => p.id !== created.id), created])
      setExpanded((prev) => ({ ...prev, [created.id]: true }))
    }
    setNewProjectName("")
    setNewProjectOpen(false)
  }

  async function commitRename(event?: FormEvent) {
    event?.preventDefault()
    if (!renamingId) return
    await renameProjectRemote(renamingId, renameValue).catch(() => undefined)
    updateProjects(renameProject(renamingId, renameValue, projects))
    setRenamingId(null)
    setRenameValue("")
  }

  const chatsById = useMemo(() => {
    const map = new Map<string, { conversation_id: string; title: string }>()
    for (const chatRow of ownerChats) map.set(chatRow.conversation_id, chatRow)
    return map
  }, [ownerChats])

  const ungroupedOwnerChats = useMemo(
    () =>
      ownerChats.filter(
        (row) =>
          !row.project_id &&
          !projects.some((project) => (project.conversationIds || []).includes(row.conversation_id)),
      ),
    [ownerChats, projects],
  )

  function modelStatus(): { label: string; tone: string } {
    if (model?.loaded) return { label: "Ready", tone: "on" }
    if (model?.loading) return { label: "Starting", tone: "load" }
    return { label: "Model off", tone: "off" }
  }

  const status = modelStatus()

  const licenseBad = useMemo(() => {
    const code = String(license?.validation?.status || license?.last_status || "").toLowerCase()
    return ["tamper_detected", "invalid_signature", "expired", "cluster_mismatch"].includes(code)
  }, [license])

  const systemDegraded = ((!model?.loaded && !model?.loading && !!model?.last_error) || licenseBad)
  const statusOnline = !systemDegraded

  const appVersion = String(diagnostics?.application_version || "0.0.0")
  const coreLabel = model?.loaded ? "STABLE" : model?.loading ? "STARTING" : "STANDBY"
  const cryptoLabel = "Keys stay on this PC"
  const sandboxLabel = String(diagnostics?.inference_backend || "local inference")
  const swarmOnline = swarmNodes.filter((n) => String(n.status).toLowerCase() === "online").length
  const swarmLabel = swarmNodes.length
    ? `${swarmOnline}/${swarmNodes.length} nodes online`
    : "Local node"

  const routes = (
    <Routes>
      <Route path="/" element={uiMode === "hud" ? <HudChatHome /> : <ChatPage />} />
      <Route path="/phone" element={<PhonePage />} />
      <Route path="/companion-pairing" element={<Navigate to="/settings/phone-pairing" replace />} />
      <Route path="/tasks/:id" element={uiMode === "hud" ? <HudChatHome /> : <ChatPage />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="/workflows" element={<WorkflowsPage />} />
      <Route path="/memory" element={<MemoryPage />} />
      <Route path="/obsidian" element={<ObsidianPage />} />
      <Route path="/model" element={<ModelPage />} />
      <Route path="/tools" element={<ToolsPage />} />
      <Route path="/mcp" element={<McpPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/settings/:submenu" element={<SettingsPage />} />
      <Route path="/license" element={<LicensePage />} />
      <Route path="/advisor" element={<AdvisorPage />} />
      <Route path="/guest-portals" element={<GuestPortalsPage />} />
      <Route path="/agents" element={<AgentsPage />} />
      <Route path="/agents/new" element={<AgentInterviewPage />} />
      <Route path="/agents/:id" element={<AgentInterviewPage />} />
      <Route path="/portability" element={<PortabilityPage />} />
      <Route path="/portability/:agentId" element={<PortabilityPage />} />
      <Route path="/context" element={<ContextRepoPage />} />
      <Route path="/trajectories" element={<TrajectoriesPage />} />
      <Route path="/trajectories/:trajectoryId" element={<TrajectoriesPage />} />
      <Route path="/environments" element={<WorkerEnvironmentsPage />} />
      <Route path="/environments/:environmentId" element={<WorkerEnvironmentsPage />} />
      <Route path="/coding" element={<CodingPage />} />
      <Route path="/coding/:taskId" element={<CodingPage />} />
      <Route path="/packs" element={<PacksPage />} />
      <Route path="/ads" element={<AdsPage />} />
      <Route path="/delegation" element={<DelegationPage />} />
      <Route path="/delegation/:taskId" element={<DelegationPage />} />
      <Route path="/system" element={<SystemPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/swarm" element={<SwarmPage />} />
      <Route path="/swarm/:nodeId" element={<SwarmPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )

  if (isSetup) {
    return (
      <div className="app setup-mode">
        <Routes>
          <Route path="/setup" element={<SetupPage />} />
          <Route path="*" element={<Navigate to="/setup" replace />} />
        </Routes>
      </div>
    )
  }

  if (uiMode === "hud") {
    return (
      <BootNova enabled>
      <HudShell
        isChat={chat}
        uiMode={uiMode}
        onUiModeChange={setUiMode}
        version={appVersion}
        statusOnline={statusOnline}
        coreLabel={coreLabel}
        cryptoLabel={cryptoLabel}
        sandboxLabel={sandboxLabel}
        swarmLabel={swarmLabel}
        tasks={recents}
        activeTaskId={currentTaskId}
        model={model}
        license={license}
        away={away}
        swarmNodes={swarmNodes}
        decisionInboxCount={decisionInboxCount}
        systemDegraded={systemDegraded}
      >
        {routes}
      </HudShell>
      </BootNova>
    )
  }

  return (
    <BootNova enabled>
    <div className={`app${navOpen ? " nav-open" : ""}${chat ? " chat-shell" : ""}`}>
      <header className="mobile-bar">
        <PortalNav variant="classic" />
        <button className="nav-toggle" type="button" aria-label="Open menu" onClick={() => setNavOpen((open) => !open)}>
          Menu
        </button>
        <strong>JARVIS</strong>
        <HelpTrigger variant="classic" onClick={() => setHelpOpen((open) => !open)} />
        <span className={`dot ${status.tone}`} />
      </header>
      <HelpPanel open={helpOpen} onClose={() => setHelpOpen(false)} variant="classic" />
      {navOpen && <button className="nav-backdrop" type="button" aria-label="Close menu" onClick={closeNav} />}
      <aside className="sidebar">
        <div className="brand">
          <strong>JARVIS</strong>
          <span>On this PC</span>
          <HelpTrigger variant="classic" onClick={() => setHelpOpen((open) => !open)} />
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
                      onClick={() => {
                        updateProjects(assignTask(project.id, currentTaskId, projects))
                        linkProjectMember(project.id, "task", currentTaskId).catch(() => undefined)
                      }}
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
                    onClick={() => {
                      deleteProjectRemote(project.id).catch(() => undefined)
                      updateProjects(deleteProject(project.id, projects))
                    }}
                  >
                    ×
                  </button>
                </div>
                {open && (
                  <div className="rail-project-tasks">
                    {(project.conversationIds || []).map((conversationId) => {
                      const chatRow = chatsById.get(conversationId)
                      return (
                        <div key={`chat-${conversationId}`} className="rail-item-row">
                          <NavLink to="/" className="rail-item" onClick={closeNav}>
                            <span className="rail-item-title">{chatRow?.title || "Chat"}</span>
                            <span className="rail-item-meta">Chat</span>
                          </NavLink>
                        </div>
                      )
                    })}
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
                            <span className="rail-item-title">{task ? taskLabel(task) : "Open task"}</span>
                            {task && ["queued", "running", "waiting"].includes(task.state || task.status) && (
                              <span className="rail-item-meta"><TaskHeartbeat task={task} label={false} />{phaseLabel(task)}</span>
                            )}
                          </NavLink>
                          <button
                            type="button"
                            className="rail-icon-btn"
                            title="Remove from project"
                            onClick={() => {
                              unlinkProjectMember("task", taskId).catch(() => undefined)
                              updateProjects(unassignTask(taskId, projects))
                            }}
                          >
                            ×
                          </button>
                        </div>
                      )
                    })}
                    {project.taskIds.length === 0 && (project.conversationIds || []).length === 0 && (
                      <p className="rail-empty">No tasks or chats in this project yet.</p>
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
                <span className="rail-item rail-item-static">
                  <span className="rail-item-title">{chatRow.title || "Chat"}</span>
                </span>
              </div>
            ))}
          </section>
        )}

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
                  <span className="rail-item-meta">
                    {["queued", "running", "waiting"].includes(task.state || task.status) && <TaskHeartbeat task={task} label={false} />}
                    {phaseLabel(task)}{grouped ? ` · ${grouped.name}` : ""}
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
          {needsSetup && <NavLink to="/setup">Setup</NavLink>}
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
          {DesktopBridge.isDesktop() && <div className="side-status-meta">Shell: {shellStatus}</div>}
        </div>
        <button type="button" className="classic-mode-toggle" onClick={() => setUiMode("hud")}>
          Switch to HUD UI
        </button>
      </aside>
      <main className={`main${chat ? " chat-main" : ""}`}>
        {routes}
      </main>
    </div>
    </BootNova>
  )
}
