import { useState, type ReactNode } from "react"
import { Link, NavLink } from "react-router-dom"
import type { AwayModeState, LicenseStatus, SwarmNode, Task } from "../api"
import { HudHealthRail } from "./HudHealthRail"
import { HudOpsRail } from "./HudOpsRail"
import type { UiMode } from "./uiMode"

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

type HudTopChromeProps = {
  version: string
  statusOnline: boolean
  uiMode: UiMode
  onUiModeChange: (mode: UiMode) => void
  adminOpen: boolean
  onAdminToggle: () => void
}

export function HudTopChrome({
  version,
  statusOnline,
  uiMode,
  onUiModeChange,
  adminOpen,
  onAdminToggle,
}: HudTopChromeProps) {
  return (
    <header className="hud-top">
      <div className="hud-top-left">
        <strong>JARVIS · NEURAL OS</strong>
        <span className="hud-top-meta">v{version}</span>
      </div>
      <div className="hud-top-center">
        <span className={`hud-status-pill${statusOnline ? "" : " degraded"}`}>
          STATUS {statusOnline ? "ONLINE" : "DEGRADED"}
        </span>
      </div>
      <div className="hud-top-right">
        <button type="button" className="hud-icon-btn" onClick={onAdminToggle} aria-expanded={adminOpen}>
          Admin
        </button>
        <button
          type="button"
          className="hud-icon-btn hud-mode-toggle"
          onClick={() => onUiModeChange(uiMode === "hud" ? "classic" : "hud")}
        >
          {uiMode === "hud" ? "Classic UI" : "HUD UI"}
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
      <div className="hud-bottom-cell">
        <span className="hud-bottom-key">CORE</span>
        <span>{coreLabel}</span>
      </div>
      <div className="hud-bottom-cell">
        <span className="hud-bottom-key">LOCAL-FIRST</span>
        <span>{cryptoLabel}</span>
      </div>
      <div className="hud-bottom-cell">
        <span className="hud-bottom-key">SANDBOX</span>
        <span>{sandboxLabel}</span>
      </div>
      <div className="hud-bottom-cell">
        <span className="hud-bottom-key">SWARM</span>
        <span>{swarmLabel}</span>
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

  return (
    <div className="hud-app">
      <HudTopChrome
        version={version}
        statusOnline={statusOnline}
        uiMode={uiMode}
        onUiModeChange={onUiModeChange}
        adminOpen={adminOpen}
        onAdminToggle={() => setAdminOpen((open) => !open)}
      />
      {isChat ? (
        <div className="hud-stage">
          <HudOpsRail tasks={tasks} activeTaskId={activeTaskId} />
          <div className="hud-center">{children}</div>
          <HudHealthRail
            model={model}
            license={license}
            away={away}
            swarmNodes={swarmNodes}
            decisionInboxCount={decisionInboxCount}
            systemDegraded={systemDegraded}
          />
        </div>
      ) : (
        <main className="hud-admin-main">{children}</main>
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
