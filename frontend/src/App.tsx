import { NavLink, Navigate, Route, Routes } from "react-router-dom"
import { useEffect, useState } from "react"
import { ChatPage } from "./pages/Chat"
import { HistoryPage } from "./pages/History"
import { ModelPage } from "./pages/Model"
import { ToolsPage } from "./pages/Tools"
import { McpPage } from "./pages/Mcp"
import { SettingsPage } from "./pages/Settings"
import { SystemPage } from "./pages/System"
import { api } from "./api"

export default function App() {
  const [model, setModel] = useState<any>(null)

  useEffect(() => {
    const tick = () => api<any>("/api/model").then(setModel).catch(() => undefined)
    tick()
    const id = setInterval(tick, 8000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <strong>JARVIS</strong>
          <span>Local desktop agent</span>
        </div>
        <nav>
          <NavLink to="/" end>Command</NavLink>
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
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/tasks/:id" element={<ChatPage />} />
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
