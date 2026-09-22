import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { useCallback, useEffect, useMemo, useState } from "react"
import { ChatPage } from "./pages/Chat"
import { OwnerChatPage } from "./pages/OwnerChat"
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
import { SkillForgePage } from "./pages/SkillForge"
import { AgentRoomsPage } from "./pages/AgentRooms"
import {
  api,
  ensureDesktopSession,
  getAwayMode,
  getDiagnostics,
  getLicenseStatus,
  getSetupStatus,
  isApiError,
  listCodingDecisionInbox,
  listSkillForgeCandidates,
  listSwarmNodes,
  skillForgeNeedsOwnerDecision,
  type AwayModeState,
  type LicenseStatus,
  type SwarmNode,
  type Task,
} from "./api"
import { collectHealthIssues, type SelfCheckSnapshot } from "./hud/systemHealth"
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
import {
  assignConversation,
  assignRepo,
  assignTask,
  createProjectRemote,
  deleteProject,
  deleteProjectRemote,
  enrichProjectsWithOwnerChats,
  fetchProjects,
  linkProjectMember,
  projectsFetchErrorMessage,
  renameProject,
  renameProjectRemote,
  unassignConversation,
  unassignRepo,
  unassignTask,
  unlinkProjectMember,
  type PortalProject,
} from "./projects"
import { ProjectsRail } from "./projects/ProjectsRail"

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
  { to: "/rooms", label: "Agent rooms" },
  { to: "/portability", label: "Portability" },
  { to: "/context", label: "Context" },
  { to: "/trajectories", label: "Trajectories" },
  { to: "/environments", label: "Environments" },
  { to: "/coding", label: "Coding" },
  { to: "/skills", label: "Modules / Skills" },
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
  return pathname === "/" || pathname.startsWith("/tasks/") || pathname.startsWith("/chats/")
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
  const [projectsLoadError, setProjectsLoadError] = useState<string | null>(null)
  const [projectsLoading, setProjectsLoading] = useState(true)
  const [projectsMigratedNotice, setProjectsMigratedNotice] = useState(false)
  const [projectsActionError, setProjectsActionError] = useState<string | null>(null)
  const [ownerChats, setOwnerChats] = useState<{ conversation_id: string; title: string; project_id?: string }[]>([])
  const [adminOpen, setAdminOpen] = useState(false)
  const [uiMode, setUiModeState] = useState<UiMode>(() => getUiMode())
  const [license, setLicense] = useState<LicenseStatus | null>(null)
  const [swarmNodes, setSwarmNodes] = useState<SwarmNode[]>([])
  const [decisionInboxCount, setDecisionInboxCount] = useState(0)
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null)
  const [selfCheck, setSelfCheck] = useState<SelfCheckSnapshot | null>(null)
  const [portalApiError, setPortalApiError] = useState<string | null>(null)

  const setUiMode = useCallback((mode: UiMode) => {
    setUiModeState(mode)
    persistUiMode(mode)
  }, [])

  const chat = isChatPath(location.pathname)
  const currentTaskId = activeTaskId(location.pathname)
  const showAdmin = adminOpen || isAdminPath(location.pathname)
  const isSetup = location.pathname.startsWith("/setup")

  useEffect(() => {
    void ensureDesktopSession()
  }, [])

  useEffect(() => {
    const tick = () =>
      api<any>("/api/model")
        .then((snap) => {
          setModel(snap)
          setPortalApiError(null)
        })
        .catch((err: unknown) => {
          if (isApiError(err) && err.status === 401) {
            setPortalApiError(
              "Authentication required. On this PC the HUD should be allowed without a key; remote LAN clients still need the owner key.",
            )
          } else if (err instanceof Error && err.message) {
            setPortalApiError(err.message)
          }
        })
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
    let cancelled = false
    setProjectsLoading(true)
    setProjectsLoadError(null)
    fetchProjects()
      .then((result) => {
        if (cancelled) return
        setProjects(result.projects)
        setProjectsMigratedNotice(result.migratedFromLocal)
        setProjectsLoadError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setProjects([])
        setProjectsLoadError(projectsFetchErrorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setProjectsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

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
      Promise.all([
        listCodingDecisionInbox(true).catch(() => ({ items: [] as { id?: string }[] })),
        listSkillForgeCandidates(undefined, 50).catch(() => ({
          candidates: [] as import("./api").SkillForgeCandidate[],
        })),
      ])
        .then(([coding, forge]) => {
          const codingOpen = coding.items?.length || 0
          const forgeOpen = (forge.candidates || []).filter(skillForgeNeedsOwnerDecision).length
          setDecisionInboxCount(codingOpen + forgeOpen)
        })
        .catch(() => undefined)
      getDiagnostics().then(setDiagnostics).catch(() => undefined)
      api<SelfCheckSnapshot>("/api/system/self-check").then(setSelfCheck).catch(() => undefined)
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

  async function runProjectAction(action: () => Promise<void>, applyLocal: () => void) {
    setProjectsActionError(null)
    try {
      await action()
      applyLocal()
    } catch (err: unknown) {
      setProjectsActionError(projectsFetchErrorMessage(err))
    }
  }

  async function handleCreateProject(name: string) {
    setProjectsActionError(null)
    try {
      const created = await createProjectRemote(name)
      setProjects((prev) => [...prev.filter((p) => p.id !== created.id), created])
    } catch (err: unknown) {
      setProjectsActionError(projectsFetchErrorMessage(err))
    }
  }

  async function handleRenameProject(projectId: string, name: string) {
    await runProjectAction(
      () => renameProjectRemote(projectId, name),
      () => setProjects((prev) => renameProject(projectId, name, prev)),
    )
  }

  async function handleDeleteProject(projectId: string) {
    await runProjectAction(
      () => deleteProjectRemote(projectId),
      () => setProjects((prev) => deleteProject(projectId, prev)),
    )
  }

  async function handleAssignTask(projectId: string, taskId: string) {
    await runProjectAction(
      () => linkProjectMember(projectId, "task", taskId),
      () => setProjects((prev) => assignTask(projectId, taskId, prev)),
    )
  }

  async function handleUnassignTask(taskId: string) {
    await runProjectAction(
      () => unlinkProjectMember("task", taskId),
      () => setProjects((prev) => unassignTask(taskId, prev)),
    )
  }

  async function handleAssignChat(projectId: string, conversationId: string) {
    await runProjectAction(
      () => linkProjectMember(projectId, "owner_chat", conversationId),
      () => setProjects((prev) => assignConversation(projectId, conversationId, prev)),
    )
  }

  async function handleUnassignChat(conversationId: string) {
    await runProjectAction(
      () => unlinkProjectMember("owner_chat", conversationId),
      () => setProjects((prev) => unassignConversation(conversationId, prev)),
    )
  }

  async function handleAssignRepo(projectId: string, repoPath: string) {
    await runProjectAction(
      () => linkProjectMember(projectId, "repo", repoPath),
      () => setProjects((prev) => assignRepo(projectId, repoPath, prev)),
    )
  }

  async function handleUnassignRepo(repoPath: string) {
    await runProjectAction(
      () => unlinkProjectMember("repo", repoPath),
      () => setProjects((prev) => unassignRepo(repoPath, prev)),
    )
  }

  const railProjects = useMemo(
    () => enrichProjectsWithOwnerChats(projects, ownerChats),
    [projects, ownerChats],
  )

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
          !railProjects.some((project) => (project.conversationIds || []).includes(row.conversation_id)),
      ),
    [ownerChats, railProjects],
  )

  const projectsRailProps = {
    projects: railProjects,
    loadError: projectsLoadError,
    loading: projectsLoading,
    migratedNotice: projectsMigratedNotice,
    actionError: projectsActionError,
    onRetryLoad: () => {
      setProjectsLoading(true)
      setProjectsLoadError(null)
      fetchProjects()
        .then((result) => {
          setProjects(result.projects)
          setProjectsMigratedNotice(result.migratedFromLocal)
        })
        .catch((err: unknown) => {
          setProjects([])
          setProjectsLoadError(projectsFetchErrorMessage(err))
        })
        .finally(() => setProjectsLoading(false))
    },
  }

  function modelStatus(): { label: string; tone: string } {
    if (model?.loaded) return { label: "Ready", tone: "on" }
    if (model?.loading) return { label: "Starting", tone: "load" }
    return { label: "Model off", tone: "off" }
  }

  const status = modelStatus()

  const healthIssues = useMemo(
    () => collectHealthIssues({ model, license, selfCheck, apiError: portalApiError }),
    [model, license, selfCheck, portalApiError],
  )
  const systemDegraded = healthIssues.length > 0
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
      <Route path="/chats/:conversationId" element={<OwnerChatPage variant={uiMode === "hud" ? "hud" : "classic"} />} />
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
      <Route path="/rooms" element={<AgentRoomsPage />} />
      <Route path="/rooms/:roomId" element={<AgentRoomsPage />} />
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
      <Route path="/skills" element={<SkillForgePage />} />
      <Route path="/skills/:candidateId" element={<SkillForgePage />} />
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
        healthIssues={healthIssues}
        projectsPanel={
          <ProjectsRail
            variant="hud"
            {...projectsRailProps}
            tasksById={tasksById}
            chatsById={chatsById}
            ungroupedOwnerChats={ungroupedOwnerChats}
            recents={recents}
            currentTaskId={currentTaskId}
            onCreateProject={handleCreateProject}
            onRenameProject={handleRenameProject}
            onDeleteProject={handleDeleteProject}
            onAssignTask={handleAssignTask}
            onUnassignTask={handleUnassignTask}
            onAssignChat={handleAssignChat}
            onUnassignChat={handleUnassignChat}
            onAssignRepo={handleAssignRepo}
            onUnassignRepo={handleUnassignRepo}
          />
        }
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
        <strong>ANZU</strong>
        <HelpTrigger variant="classic" onClick={() => setHelpOpen((open) => !open)} />
        <span className={`dot ${status.tone}`} />
      </header>
      <HelpPanel open={helpOpen} onClose={() => setHelpOpen(false)} variant="classic" />
      {navOpen && <button className="nav-backdrop" type="button" aria-label="Close menu" onClick={closeNav} />}
      <aside className="sidebar">
        <div className="brand">
          <strong>ANZU</strong>
          <span>Local Superassistant</span>
          <HelpTrigger variant="classic" onClick={() => setHelpOpen((open) => !open)} />
        </div>

        <NavLink to="/" end className="rail-new" onClick={closeNav}>
          New task
        </NavLink>

        <ProjectsRail
          variant="classic"
          {...projectsRailProps}
          tasksById={tasksById}
          chatsById={chatsById}
          ungroupedOwnerChats={ungroupedOwnerChats}
          recents={recents}
          currentTaskId={currentTaskId}
          onCreateProject={handleCreateProject}
          onRenameProject={handleRenameProject}
          onDeleteProject={handleDeleteProject}
          onAssignTask={handleAssignTask}
          onUnassignTask={handleUnassignTask}
          onAssignChat={handleAssignChat}
          onUnassignChat={handleUnassignChat}
          onAssignRepo={handleAssignRepo}
          onUnassignRepo={handleUnassignRepo}
          onCloseNav={closeNav}
        />

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
          To stop ANZU, use <strong>Stop</strong> on the Windows tray. This window is for talking and settings.
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
