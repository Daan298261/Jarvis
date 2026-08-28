import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { useEffect, useState } from "react"
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
import { SetupPage } from "./pages/Setup"
import { api, getSetupStatus } from "./api"
import { DesktopBridge, type BackendLifecycleStatus } from "./desktop/bridge"

export default function App() {
  const [model, setModel] = useState<any>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null)
  const [shellStatus, setShellStatus] = useState<BackendLifecycleStatus>("unknown")
  const location = useLocation()
  const navigate = useNavigate()
  const isSetup = location.pathname.startsWith("/setup")
  const isPhone = location.pathname.startsWith("/phone")

  useEffect(() => {
    const tick = () => api<any>("/api/model").then(setModel).catch(() => undefined)
    tick()
    const id = setInterval(tick, 8000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    getSetupStatus()
      .then((s) => {
        setNeedsSetup(s.needs_setup)
        if (s.needs_setup && !location.pathname.startsWith("/setup") && !location.pathname.startsWith("/phone")) {
          navigate("/setup", { replace: true })
        }
      })
      .catch(() => setNeedsSetup(false))
  }, [location.pathname, navigate])

  useEffect(() => {
    if (!DesktopBridge.isDesktop()) return
    const tick = () => DesktopBridge.backendStatus().then(setShellStatus).catch(() => undefined)
    tick()
    const id = setInterval(tick, 4000)
    return () => clearInterval(id)
  }, [])

  function closeNav() {
    setNavOpen(false)
  }

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

  return (
    <div className={`app${navOpen ? " nav-open" : ""}`}>
      <header className="mobile-bar">
        <button className="nav-toggle" type="button" aria-label="Open menu" onClick={() => setNavOpen((open) => !open)}>
          Menu
        </button>
        <strong>JARVIS</strong>
        <span className={`dot ${model?.loaded ? "on" : model?.loading ? "load" : "off"}`} />
      </header>
      {navOpen && <button className="nav-backdrop" type="button" aria-label="Close menu" onClick={closeNav} />}
      {!isPhone && (
        <aside className="sidebar">
          <div className="brand">
            <strong>JARVIS</strong>
            <span>Local desktop agent</span>
          </div>
          <nav onClick={closeNav}>
            <NavLink to="/" end>Command</NavLink>
            <NavLink to="/phone">Phone</NavLink>
            <NavLink to="/history">History</NavLink>
            <NavLink to="/workflows">Guide & Workflows</NavLink>
            <NavLink to="/memory">Memory</NavLink>
            <NavLink to="/model">Model</NavLink>
            <NavLink to="/tools">Tools</NavLink>
            <NavLink to="/mcp">MCP</NavLink>
            <NavLink to="/settings">Settings</NavLink>
            <NavLink to="/system">System</NavLink>
            <NavLink to="/swarm">Swarm</NavLink>
            {needsSetup && <NavLink to="/setup">Setup</NavLink>}
          </nav>
          <div className="side-status">
            <div>
              <span className={`dot ${model?.loaded ? "on" : model?.loading ? "load" : "off"}`} />
              {model?.loaded ? `${model.active_model || "Model"} loaded` : model?.loading ? "Loading model" : "Model unloaded"}
            </div>
            <div style={{ marginTop: 8 }}>{model?.quantization} · {model?.profile}</div>
            {DesktopBridge.isDesktop() && (
              <div style={{ marginTop: 8 }}>
                Shell: {shellStatus}
              </div>
            )}
          </div>
        </aside>
      )}
      <main className="main">
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
          <Route path="/system" element={<SystemPage />} />
          <Route path="/swarm" element={<SwarmPage />} />
          <Route path="/swarm/:nodeId" element={<SwarmPage />} />
          <Route path="/setup" element={<SetupPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
