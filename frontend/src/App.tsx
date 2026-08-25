import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom"
import { useEffect, useState } from "react"
import { ChatPage } from "./pages/Chat"
import { HistoryPage } from "./pages/History"
import { ModelPage } from "./pages/Model"
import { ToolsPage } from "./pages/Tools"
import { McpPage } from "./pages/Mcp"
import { SettingsPage } from "./pages/Settings"
import { SystemPage } from "./pages/System"
import { VoicePage } from "./pages/Voice"
import { PhonePage } from "./pages/Phone"
import { api, getAuthToken, onAuthFailure, setAuthToken } from "./api"

export default function App() {
  const { pathname } = useLocation()
  if (pathname === "/phone" || pathname.startsWith("/phone/")) {
    return (
      <div className="phone-app">
        <AuthBanner />
        <PhonePage />
      </div>
    )
  }
  return <DesktopApp />
}

function AuthBanner() {
  const [authBlock, setAuthBlock] = useState<{ status: number; detail: string } | null>(null)
  const [tokenDraft, setTokenDraft] = useState(getAuthToken)
  useEffect(() => onAuthFailure((event) => setAuthBlock(event)), [])
  if (!authBlock) return null
  return (
    <div className="card" style={{ margin: "12px 12px 0" }}>
      <h2>LAN authentication</h2>
      <p className="lede">{authBlock.detail}</p>
      <label>Session token
        <input type="password" autoComplete="off" value={tokenDraft} onChange={(e) => setTokenDraft(e.target.value)} />
      </label>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn" type="button" onClick={() => { setAuthToken(tokenDraft); setAuthBlock(null) }}>Use token</button>
      </div>
    </div>
  )
}

function DesktopApp() {
  const [sys, setSys] = useState<any>(null)
  const [authBlock, setAuthBlock] = useState<{ status: number; detail: string } | null>(null)
  const [tokenDraft, setTokenDraft] = useState(getAuthToken)

  useEffect(() => onAuthFailure((event) => setAuthBlock(event)), [])

  useEffect(() => {
    const tick = () => api<any>("/api/system").then((payload) => {
      setSys(payload)
      setAuthBlock(null)
    }).catch(() => undefined)
    tick()
    const id = setInterval(tick, 12000)
    return () => clearInterval(id)
  }, [])
  const model = sys?.model
  const summary = sys?.hardware_view?.summary
  const autonomy = sys?.autonomy_mode

  function saveSessionToken() {
    setAuthToken(tokenDraft)
    api<any>("/api/system").then((payload) => {
      setSys(payload)
      setAuthBlock(null)
    }).catch(() => undefined)
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <strong>JARVIS</strong>
          <span>Local desktop agent</span>
        </div>
        <nav>
          <NavLink to="/" end>Command</NavLink>
          <NavLink to="/phone">Phone</NavLink>
          <NavLink to="/voice">Voice</NavLink>
          <NavLink to="/history">History</NavLink>
          <NavLink to="/model">Model</NavLink>
          <NavLink to="/tools">Tools</NavLink>
          <NavLink to="/mcp">MCP</NavLink>
          <NavLink to="/settings">Settings</NavLink>
          <NavLink to="/system">System</NavLink>
        </nav>
        <div className="side-status">
          <div>
            <span className={`dot ${model?.loaded ? "on" : model?.loading ? "load" : "off"}`} />
            {model?.loaded ? "Qwen3.5-27B loaded" : model?.loading ? "Loading model" : "Model unloaded"}
          </div>
          <div style={{ marginTop: 8 }}>{model?.quantization} · {model?.profile}</div>
          {summary ? <div style={{ marginTop: 8 }}>{summary}</div> : null}
          {autonomy ? <div style={{ marginTop: 8 }}>Autonomy: {autonomy.label}</div> : null}
        </div>
      </aside>
      <main className="main">
        {authBlock ? (
          <div className="card" style={{ marginBottom: 16 }}>
            <h2>LAN authentication</h2>
            <p className="lede">{authBlock.detail}</p>
            <label>Session token (JARVIS_AUTH_TOKEN)
              <input
                type="password"
                autoComplete="off"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
              />
            </label>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" type="button" onClick={saveSessionToken}>Use token</button>
            </div>
          </div>
        ) : null}
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/tasks/:id" element={<ChatPage />} />
          <Route path="/voice" element={<VoicePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/model" element={<ModelPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/mcp" element={<McpPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
