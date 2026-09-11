import { useState, type ReactNode } from "react"
import { Link, NavLink } from "react-router-dom"
import type { AwayModeState, LicenseStatus, SwarmNode, Task } from "../api"
import { HudHealthRail } from "./HudHealthRail"
import { HudModelSelector } from "./HudModelSelector"
import { HudOpsRail } from "./HudOpsRail"
import type { UiMode } from "./uiMode"
import "./hud.css"
import "./hud-v2.css"

const ADMIN_QUICK = [
  { to: "/settings", label: "Settings" },
  { to: "/swarm", label: "Swarm" },
  { to: "/memory", label: "Memory" },
  { to: "/history", label: "History" },
  { to: "/workflows", label: "Workflows" },
  { to: "/phone", label: "Phone" },
  { to: "/license", label: "License" },
  { to: "/system", label: "System" },
] as const

type HudPanel = "activity" | "system" | null

type HudTopChromeProps = {
  version: string
  statusOnline: boolean
  uiMode: UiMode
  onUiModeChange: (mode: UiMode) => void
  adminOpen: boolean
  onAdminToggle: () => void
  panel: HudPanel
  onPanelToggle: (panel: Exclude<HudPanel, null>) => void
  showPanels: boolean
  runningCount: number
  attentionCount: number
  model: { loaded?: boolean; loading?: boolean; active_model?: string; last_error?: string } | null
}

export function HudTopChrome({
  version,
  statusOnline,
  uiMode,
  onUiModeChange,
  adminOpen,
  onAdminToggle,
  panel,
  onPanelToggle,
  showPanels,
  runningCount,
  attentionCount,
  model,
}: HudTopChromeProps) {
  return (
    <header className="hud-top">
      <div className="hud-top-left">
        <div className="hud-brand-lockup">
          <span className={`hud-brand-mark${statusOnline ? "" : " degraded"}`} aria-hidden />
          <strong>JARVIS</strong>
        </div>
        <span className={`hud-local-state${statusOnline ? "" : " degraded"}`}>
          LOCAL · {statusOnline ? "ONLINE" : "DEGRADED"}
        </span>
        <span className="hud-top-meta">v{version}</span>
      </div>

      <div className="hud-top-center">
        {showPanels && (
          <>
            <button
              type="button"
              className={`hud-panel-toggle${panel === "activity" ? " active" : ""}`}
              onClick={() => onPanelToggle("activity")}
              aria-expanded={panel === "activity"}
            >
              Activity
              {runningCount > 0 && <span className="hud-count">{runningCount}</span>}
            </button>
            <button
              type="button"
              className={`hud-panel-toggle${panel === "system" ? " active" : ""}${attentionCount > 0 ? " attention" : ""}`}
              onClick={() => onPanelToggle("system")}
              aria-expanded={panel === "system"}
            >
              System
              {attentionCount > 0 && <span className="hud-count">{attentionCount}</span>}
            </button>
          </>
        )}
      </div>

      <div className="hud-top-right">
        <HudModelSelector model={model} />
        <button type="button" className="hud-icon-btn" onClick={onAdminToggle} aria-expanded={adminOpen}>
          Admin
        </button>
        <button
          type="button"
          className="hud-icon-btn hud-mode-toggle"
          onClick={() => onUiModeChange(uiMode === "hud" ? "classic" : "hud")}
        >
          Legacy UI
        </button>
      </div>

      {adminOpen && (
        <nav className="hud-admin-drawer" aria-label="Admin navigation">
          <NavLink to="/" end>New task</NavLink>
          {ADMIN_QUICK.map((link) => (
            <NavLink key={link.to} to={link.to}>{link.label}</NavLink>
          ))}
          <Link to="/agents">Agents</Link>
          <Link to="/coding">Coding</Link>
          <Link to="/environments">Environments</Link>
          <Link to="/model">Model</Link>
          <Link to="/tools">Tools</Link>
          <Link to="/mcp">MCP</Link>
        </nav>
      )}
    </header>
  )
}

type HudBottomChromeProps = {
  coreLabel: string
  cryptoLabel: string
  sandboxLabel: string
  swarmLabel: string
}

export function HudBottomChrome({ coreLabel, cryptoLabel, sandboxLabel, swarmLabel }: HudBottomChromeProps) {
  return (
    <footer className="hud-bottom">
      <div className="hud-bottom-group">
        <span className="hud-bottom-live" aria-hidden />
        <span>{coreLabel}</span>
        <span className="hud-bottom-sep">·</span>
        <span>{swarmLabel}</span>
      </div>
      <div className="hud-bottom-group">
        <span>{cryptoLabel}</span>
        <span className="hud-bottom-sep">·</span>
        <span>{sandboxLabel}</span>
      </div>
    </footer>
  )
}

export type HudShellProps = {
  children: ReactNode
  isChat: boolean
  uiMode: UiMode
  onUiModeChange: (mode: UiMode) => void
  version: string
  statusOnline: boolean
  coreLabel: string
  cryptoLabel: string
  sandboxLabel: string
  swarmLabel: string
  tasks: Task[]
  activeTaskId?: string
  model: { loaded?: boolean; loading?: boolean; active_model?: string; last_error?: string } | null
  license: LicenseStatus | null
  away: AwayModeState | null
  swarmNodes: SwarmNode[]
  decisionInboxCount: number
  systemDegraded: boolean
}

export function HudShell({
  children,
  isChat,
  uiMode,
  onUiModeChange,
  version,
  statusOnline,
  coreLabel,
  cryptoLabel,
  sandboxLabel,
  swarmLabel,
  tasks,
  activeTaskId,
  license,
  away,
  swarmNodes,
  decisionInboxCount,
  systemDegraded,
  model,
}: HudShellProps) {
  const [adminOpen, setAdminOpen] = useState(false)
  const [panel, setPanel] = useState<HudPanel>(null)

  const runningCount = tasks.filter((task) => ["running", "queued", "waiting"].includes(task.status)).length
  const attentionCount = decisionInboxCount + (systemDegraded ? 1 : 0)

  function togglePanel(next: Exclude<HudPanel, null>) {
    setAdminOpen(false)
    setPanel((current) => current === next ? null : next)
  }

  function toggleAdmin() {
    setPanel(null)
    setAdminOpen((open) => !open)
  }

  function closePanels() {
    setPanel(null)
    setAdminOpen(false)
  }

  return (
    <div className="hud-app">
      <HudTopChrome
        version={version}
        statusOnline={statusOnline}
        uiMode={uiMode}
        onUiModeChange={onUiModeChange}
        adminOpen={adminOpen}
        onAdminToggle={toggleAdmin}
        panel={panel}
        onPanelToggle={togglePanel}
        showPanels={isChat}
        runningCount={runningCount}
        attentionCount={attentionCount}
        model={model}
      />

      {isChat ? (
        <div className="hud-stage">
          <div className="hud-center">{children}</div>
        </div>
      ) : (
        <main className="hud-admin-main">{children}</main>
      )}

      {isChat && panel && (
        <>
          <button className="hud-panel-backdrop" type="button" aria-label="Close panel" onClick={closePanels} />
          {panel === "activity" && (
            <aside className="hud-drawer hud-drawer-left" aria-label="Activity panel">
              <button className="hud-drawer-close" type="button" aria-label="Close activity" onClick={closePanels}>×</button>
              <HudOpsRail tasks={tasks} activeTaskId={activeTaskId} />
            </aside>
          )}
          {panel === "system" && (
            <aside className="hud-drawer hud-drawer-right" aria-label="System panel">
              <button className="hud-drawer-close" type="button" aria-label="Close system" onClick={closePanels}>×</button>
              <HudHealthRail
                model={model}
                license={license}
                away={away}
                swarmNodes={swarmNodes}
                decisionInboxCount={decisionInboxCount}
                systemDegraded={systemDegraded}
              />
            </aside>
          )}
        </>
      )}

      <HudBottomChrome
        coreLabel={coreLabel}
        cryptoLabel={cryptoLabel}
        sandboxLabel={sandboxLabel}
        swarmLabel={swarmLabel}
      />
    </div>
  )
}
