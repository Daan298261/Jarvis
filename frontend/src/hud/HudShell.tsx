import { useEffect, useState, type ReactNode } from "react"
import { refreshSessionPersonality } from "./sessionPersonality"
import { Link, NavLink, useLocation } from "react-router-dom"
import type { AwayModeState, LicenseStatus, SwarmNode, Task } from "../api"
import { HelpPanel, HelpTrigger } from "../help/HelpPanel"
import { PortalNav } from "../components/PortalNav"
import { HudHealthRail } from "./HudHealthRail"
import { HudLocalStatus } from "./HudLocalStatus"
import { HudModelSelector } from "./HudModelSelector"
import { HudPersonalityRail } from "./HudPersonalityRail"
import { HudOpsRail } from "./HudOpsRail"
import type { UiMode } from "./uiMode"
import { HudOverlayProvider, useHudOverlay } from "./hudOverlayContext"
import { useHexStrikeSuiteActive } from "./hexstrikeSuite"
import type { HealthIssue } from "./systemHealth"
import { HudStarfield } from "./HudStarfield"
import "./hud.css"
import "./hud-v2.css"

const ADMIN_QUICK = [
  { to: "/settings", label: "Settings" },
  { to: "/swarm", label: "Swarm" },
  { to: "/obsidian", label: "Obsidian" },
  { to: "/memory", label: "Memory" },
  { to: "/history", label: "History" },
  { to: "/workflows", label: "Workflows" },
  { to: "/phone", label: "Phone" },
  { to: "/license", label: "License" },
  { to: "/system", label: "System" },
] as const

type HudPanel = "activity" | "system" | "projects" | null

type HudTopChromeProps = {
  version: string
  statusOnline: boolean
  uiMode: UiMode
  onUiModeChange: (mode: UiMode) => void
  adminOpen: boolean
  onAdminToggle: () => void
  helpOpen: boolean
  onHelpToggle: () => void
  panel: HudPanel
  onPanelToggle: (panel: Exclude<HudPanel, null>) => void
  showPanels: boolean
  runningCount: number
  attentionCount: number
  model: { loaded?: boolean; loading?: boolean; active_model?: string; last_error?: string } | null
  onModelMenuOpenChange?: (open: boolean) => void
  hexStrikeActive?: boolean
  hexSuiteExpanded?: boolean
  onDaybreakToggle?: () => void
  onAdminNav?: () => void
  healthIssues?: HealthIssue[]
}

export function HudTopChrome({
  version,
  statusOnline,
  uiMode,
  onUiModeChange,
  adminOpen,
  onAdminToggle,
  helpOpen,
  onHelpToggle,
  panel,
  onPanelToggle,
  showPanels,
  runningCount,
  attentionCount,
  model,
  onModelMenuOpenChange,
  hexStrikeActive = false,
  hexSuiteExpanded = false,
  onDaybreakToggle,
  onAdminNav,
  healthIssues = [],
}: HudTopChromeProps) {
  return (
    <header className="hud-top">
      <div className="hud-top-left">
        <PortalNav variant="hud" />
        <div className="hud-brand-lockup">
          <Link to="/" className="hud-brand-link" title="New task">
            <span className={`hud-brand-mark${statusOnline ? "" : " degraded"}`} aria-hidden />
            <strong>JARVIS</strong>
          </Link>
        </div>
        <HudLocalStatus statusOnline={statusOnline} issues={healthIssues} />
        <span className="hud-top-meta">v{version}</span>
      </div>

      <div className="hud-top-center">
        {hexStrikeActive && (
          <button
            type="button"
            className={`hud-panel-toggle hud-daybreak-toggle${hexSuiteExpanded ? " active" : ""}`}
            onClick={() => onDaybreakToggle?.()}
            aria-pressed={hexSuiteExpanded}
            title={hexSuiteExpanded ? "Return to HUD presence" : "Open Daybreak operator console"}
          >
            {hexSuiteExpanded ? "HUD" : "Daybreak"}
          </button>
        )}
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
              className={`hud-panel-toggle${panel === "projects" ? " active" : ""}`}
              onClick={() => onPanelToggle("projects")}
              aria-expanded={panel === "projects"}
            >
              Projects
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
        <HelpTrigger variant="hud" onClick={onHelpToggle} expanded={helpOpen} />
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
        <HudModelSelector model={model} onOpenChange={onModelMenuOpenChange} />
      </div>

      {adminOpen && (
        <nav className="hud-admin-drawer" aria-label="Admin navigation">
          <NavLink to="/" end onClick={() => onAdminNav?.()}>New task</NavLink>
          {ADMIN_QUICK.map((link) => (
            <NavLink key={link.to} to={link.to} onClick={() => onAdminNav?.()}>{link.label}</NavLink>
          ))}
          <Link to="/agents" onClick={() => onAdminNav?.()}>Agents</Link>
          <Link to="/coding" onClick={() => onAdminNav?.()}>Coding</Link>
          <Link to="/environments" onClick={() => onAdminNav?.()}>Environments</Link>
          <Link to="/model" onClick={() => onAdminNav?.()}>Model</Link>
          <Link to="/tools" onClick={() => onAdminNav?.()}>Tools</Link>
          <Link to="/mcp" onClick={() => onAdminNav?.()}>MCP</Link>
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
  healthIssues?: HealthIssue[]
  projectsPanel?: ReactNode
}

export function HudShell(props: HudShellProps) {
  return (
    <HudOverlayProvider>
      <HudShellInner {...props} />
    </HudOverlayProvider>
  )
}

function HudShellInner({
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
  healthIssues = [],
  model,
  projectsPanel,
}: HudShellProps) {
  const { active: hexStrikeActive } = useHexStrikeSuiteActive()
  const { hexSuiteExpanded, toggleHexSuite, dismissHexSuiteForOverlay } = useHudOverlay()
  const location = useLocation()
  const [adminOpen, setAdminOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [panel, setPanel] = useState<HudPanel>(null)
  const [modelMenuOpen, setModelMenuOpen] = useState(false)
  const [personalityOpen, setPersonalityOpen] = useState(false)

  useEffect(() => {
    refreshSessionPersonality().catch(() => undefined)
    const id = window.setInterval(() => refreshSessionPersonality().catch(() => undefined), 12000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    setPanel(null)
    setAdminOpen(false)
    setHelpOpen(false)
    setPersonalityOpen(false)
  }, [location.pathname])

  const runningCount = tasks.filter((task) => ["running", "queued", "waiting"].includes(task.status)).length
  const attentionCount = decisionInboxCount + (systemDegraded ? 1 : 0)

  function togglePanel(next: Exclude<HudPanel, null>) {
    setAdminOpen(false)
    setHelpOpen(false)
    setPersonalityOpen(false)
    dismissHexSuiteForOverlay()
    setPanel((current) => current === next ? null : next)
  }

  function toggleAdmin() {
    setPanel(null)
    setHelpOpen(false)
    setPersonalityOpen(false)
    setAdminOpen((open) => {
      const next = !open
      if (next) dismissHexSuiteForOverlay()
      return next
    })
  }

  function toggleHelp() {
    setPanel(null)
    setAdminOpen(false)
    setPersonalityOpen(false)
    setHelpOpen((open) => {
      const next = !open
      if (next) dismissHexSuiteForOverlay()
      return next
    })
  }

  function closeAdminDrawer() {
    setAdminOpen(false)
  }

  function closePanels() {
    setPanel(null)
    setAdminOpen(false)
    setHelpOpen(false)
    setPersonalityOpen(false)
  }

  function togglePersonality() {
    setPanel(null); setAdminOpen(false); setHelpOpen(false); setModelMenuOpen(false); dismissHexSuiteForOverlay(); setPersonalityOpen(v=>!v)
  }

  function onDaybreakToggle() {
    closePanels()
    toggleHexSuite()
  }

  const skyOpen = !isChat || adminOpen || helpOpen || personalityOpen || panel !== null || modelMenuOpen
  const pulseKey = `${location.pathname}|${skyOpen ? "sky" : "cluster"}|${panel ?? ""}|${adminOpen}|${helpOpen}`

  return (
    <div className={`hud-app${skyOpen ? " hud-sky" : ""}`}>
      <HudStarfield mode={skyOpen ? "sky" : "cluster"} pulseKey={pulseKey} />
      <HudTopChrome
        version={version}
        statusOnline={statusOnline}
        uiMode={uiMode}
        onUiModeChange={onUiModeChange}
        adminOpen={adminOpen}
        onAdminToggle={toggleAdmin}
        helpOpen={helpOpen}
        onHelpToggle={toggleHelp}
        panel={panel}
        onPanelToggle={togglePanel}
        showPanels
        runningCount={runningCount}
        attentionCount={attentionCount}
        model={model}
        hexStrikeActive={hexStrikeActive}
        hexSuiteExpanded={hexSuiteExpanded}
        onDaybreakToggle={onDaybreakToggle}
        onAdminNav={closeAdminDrawer}
        healthIssues={healthIssues}
        onModelMenuOpenChange={(open) => {
          setModelMenuOpen(open)
          if (open) {
            setAdminOpen(false)
            setHelpOpen(false)
            dismissHexSuiteForOverlay()
          }
        }}
      />
      <HudPersonalityRail open={personalityOpen} onToggle={togglePersonality} onSelected={()=>setPersonalityOpen(false)} />
      <HelpPanel open={helpOpen} onClose={() => setHelpOpen(false)} variant="hud" />

      {isChat ? (
        <div className="hud-stage">
          <div className="hud-center">{children}</div>
        </div>
      ) : (
        <>
          <div className="hud-admin-nav">
            <PortalNav variant="hud" />
          </div>
          <main className="hud-admin-main" key={location.pathname}>{children}</main>
        </>
      )}

      {panel && (
        <>
          <button className="hud-panel-backdrop" type="button" aria-label="Close panel" onClick={closePanels} />
          {panel === "activity" && (
            <aside className="hud-drawer hud-drawer-left" aria-label="Activity panel">
              <button className="hud-drawer-close" type="button" aria-label="Close activity" onClick={closePanels}>×</button>
              <HudOpsRail tasks={tasks} activeTaskId={activeTaskId} />
            </aside>
          )}
          {panel === "projects" && (
            <aside className="hud-drawer hud-drawer-left hud-projects-drawer" aria-label="Projects panel">
              <button className="hud-drawer-close" type="button" aria-label="Close projects" onClick={closePanels}>×</button>
              {projectsPanel}
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
                healthIssues={healthIssues}
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
