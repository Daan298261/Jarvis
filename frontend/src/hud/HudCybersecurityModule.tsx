import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  cybersecurityToolSupportsProcessControl,
  downloadModuleCatalogEntry,
  loadCybersecurityModuleCatalog,
  openCybersecurityToolFolder,
  setCybersecurityModuleEnabled,
  setCybersecurityToolEnabled,
  startCybersecurityTool,
  stopCybersecurityTool,
  type CybersecurityModule,
  type CybersecurityToolMember,
} from "../api"
import { settingsSubmenuPath } from "../settings/settingsSubmenus"
import "./cybersecurityModule.css"

type CatalogLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; module: CybersecurityModule }

function roleLabel(role: string): string {
  return role.replace(/_/g, " ").replace(/\//g, " / ")
}

function statusHint(status: CybersecurityToolMember["status"]): string {
  switch (status) {
    case "missing":
      return "Clone not on disk — use Download to fetch from the allowlisted source."
    case "found":
      return "Checkout found locally."
    case "starting":
      return "Process is starting."
    case "running":
      return "Jarvis-managed process is running."
    case "error":
      return "Last operation reported an error — check backend logs."
    case "disabled":
      return "Disabled in module settings."
    default:
      return ""
  }
}

export function HudCybersecurityModule() {
  const [loadState, setLoadState] = useState<CatalogLoadState>({ status: "loading" })
  const [busy, setBusy] = useState(false)
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const [message, setMessage] = useState("")

  const refresh = useCallback(async () => {
    const result = await loadCybersecurityModuleCatalog()
    if (result.ok) {
      setLoadState({ status: "ready", module: result.module })
    } else {
      setLoadState({ status: "error", message: result.message })
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => window.clearInterval(timer)
  }, [refresh])

  async function runModuleAction(action: () => Promise<{ ok: boolean; message: string }>) {
    setBusy(true)
    setMessage("")
    try {
      const result = await action()
      setMessage(result.message)
      if (result.ok) await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function runRowAction(toolId: string, action: () => Promise<{ ok: boolean; message: string }>) {
    setRowBusy(toolId)
    setMessage("")
    try {
      const result = await action()
      setMessage(result.message)
      if (result.ok) await refresh()
    } finally {
      setRowBusy(null)
    }
  }

  if (loadState.status === "loading") {
    return <p className="jarvis-cyber-module-banner">Loading cybersecurity module…</p>
  }

  if (loadState.status === "error") {
    return (
      <div className="jarvis-cyber-module">
        <p className="jarvis-cyber-module-banner warn" role="alert">
          Could not load the cybersecurity module catalog: {loadState.message}
        </p>
        <button
          type="button"
          className="jarvis-cyber-module-retry"
          disabled={busy}
          onClick={() => {
            setLoadState({ status: "loading" })
            void refresh()
          }}
        >
          Retry
        </button>
      </div>
    )
  }

  const module = loadState.module
  const masterDisabled = busy
  const foundCount = module.members.filter((m) => m.status === "found" || m.status === "running").length

  return (
    <div className="jarvis-cyber-module">
      <div className="jarvis-cyber-module-head">
        <h3 className="jarvis-cyber-module-title">Module · six optional backends</h3>
        <div className="jarvis-cyber-module-master">
          <span>
            {module.enabled ? "Enabled" : "Disabled"}
            {` · ${foundCount}/${module.members.length} local`}
          </span>
          <button
            type="button"
            disabled={masterDisabled}
            title={module.enabled ? "Disable entire cybersecurity module" : "Enable cybersecurity module"}
            onClick={() =>
              void runModuleAction(async () => {
                const next = !module.enabled
                return setCybersecurityModuleEnabled(next)
              })
            }
          >
            {module.enabled ? "Disable module" : "Enable module"}
          </button>
        </div>
      </div>

      {message && (
        <p className="jarvis-cyber-module-msg" aria-live="polite">
          {message}
        </p>
      )}

      <ul className="jarvis-cyber-tool-list" aria-label="Cybersecurity module tools">
        {module.members.map((member) => {
          const rowLocked = busy || rowBusy === member.id
          const moduleOff = !module.enabled
          const pathKnown = Boolean(member.local_path)
          const canOpenFolder = pathKnown && !rowLocked
          const canDownload = !rowLocked && (member.status === "missing" || !pathKnown)
          const processControl = cybersecurityToolSupportsProcessControl(member.role)
          const canStart =
            !rowLocked &&
            !moduleOff &&
            member.enabled &&
            processControl &&
            member.status !== "running" &&
            member.status !== "starting" &&
            (pathKnown || member.status === "found")
          const canStop =
            !rowLocked && processControl && (member.status === "running" || member.status === "starting")
          const toggleDisabled = rowLocked || moduleOff

          return (
            <li
              key={member.id}
              className={`jarvis-cyber-tool-row${moduleOff || !member.enabled ? " disabled" : ""}`}
            >
              <div className="jarvis-cyber-tool-row-head">
                <div className="jarvis-cyber-tool-name">
                  {member.display_name}
                  <span className="jarvis-cyber-tool-meta">
                    {roleLabel(member.role)} · {statusHint(member.status)}
                  </span>
                </div>
                <span className={`jarvis-cyber-status ${member.status}`} title={statusHint(member.status)}>
                  {member.status}
                </span>
              </div>

              {member.local_path ? (
                <p className="jarvis-cyber-tool-path" title={member.local_path}>
                  {member.local_path}
                </p>
              ) : (
                <p className="jarvis-cyber-tool-path">Local path unknown</p>
              )}

              <div className="jarvis-cyber-tool-actions">
                <button
                  type="button"
                  className={member.enabled ? "primary" : undefined}
                  disabled={toggleDisabled}
                  title={
                    moduleOff
                      ? "Enable the module first."
                      : member.enabled
                        ? "Disable this tool"
                        : "Enable this tool"
                  }
                  onClick={() =>
                    void runRowAction(member.id, () => setCybersecurityToolEnabled(member.id, !member.enabled))
                  }
                >
                  {member.enabled ? "Enabled" : "Enable tool"}
                </button>
                <button
                  type="button"
                  disabled={!canOpenFolder}
                  title={!pathKnown ? "No local path yet." : "Open clone in file manager"}
                  onClick={() => void runRowAction(member.id, () => openCybersecurityToolFolder(member.id))}
                >
                  Open folder
                </button>
                <button
                  type="button"
                  disabled={!canDownload}
                  title={
                    canDownload
                      ? "Clone or refresh from allowlisted source"
                      : "Already on disk — use Open folder"
                  }
                  onClick={() => void runRowAction(member.id, () => downloadModuleCatalogEntry(member.id))}
                >
                  Download
                </button>
                {processControl && (
                  <>
                    <button
                      type="button"
                      disabled={!canStart}
                      title={
                        !processControl
                          ? "This connector is register-only."
                          : "Start Jarvis-managed process"
                      }
                      onClick={() => void runRowAction(member.id, () => startCybersecurityTool(member.id))}
                    >
                      Start
                    </button>
                    <button
                      type="button"
                      disabled={!canStop}
                      title="Stop Jarvis-managed process"
                      onClick={() => void runRowAction(member.id, () => stopCybersecurityTool(member.id))}
                    >
                      Stop
                    </button>
                  </>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      <p className="jarvis-cyber-module-links">
        HexStrike stays the defensive suite beside this module. Optional:{" "}
        <Link to="/packs">Module catalog (Packs)</Link>
        {" · "}
        <Link to={settingsSubmenuPath("advanced")}>Advanced settings</Link>
      </p>
    </div>
  )
}
